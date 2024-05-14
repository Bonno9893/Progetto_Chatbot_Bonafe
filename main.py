import logging
import time
import nltk
from nltk.corpus import wordnet
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from google.cloud import vision, storage, translate_v2
from secret import bot_token
from fuzzywuzzy import process

nltk.download('wordnet')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

vision_client = vision.ImageAnnotatorClient()
storage_client = storage.Client()
bucket = storage_client.get_bucket('photo_chatbot')
translate_client = translate_v2.Client()

last_upload_time = {}

def help_button():
    keyboard = [[InlineKeyboardButton("Aiuto", callback_data='help')]]
    return InlineKeyboardMarkup(keyboard)

def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    if query.data == 'help':
        help_command(update, context)

def handle_invalid_command(update, context):
    update.message.reply_text("""
Comando non valido!
Potresti aver scritto uno dei comandi previsti in modo errato, per esempio senza la maiuscola iniziale...
Prova di nuovo o clicca il pulsante di aiuto, ti invierò di nuovo i comandi da utilizzare nella forma corretta!.""", reply_markup=help_button())

def start(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton("Aiuto", callback_data='help')]]
    user_first_name = update.message.from_user.first_name
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(f'Ciao {user_first_name}! Premi il pulsante qui sotto per ottenere aiuto.', reply_markup=reply_markup)

def help_command(update: Update, context: CallbackContext):
    help_text = """
Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Per interagire con me scrivi in chat qui sotto i seguenti comandi:

1. Invia una o più immagini, le conserverò per te!
2. Se invii una sola immagine, puoi scrivere una descrizione personalizzata, composta da una o più parole prima dell'invio. Questa ti aiuterà a trovarla più facilmente!
3. Per cercare un'immagine corrispondente ad una tua descrizione utilizza il comando "Cerca immagine [parola chiave]" (es. Cerca immagine gatto). Utilizza una sola parola per descrivere l'immagine!
4. Per cercare tutte le immagini corrispondenti ad una tua descrizione utilizza il comando "Cerca tutte le immagini [parola chiave]" (es. Cerca tutte le immagini gatto). Utilizza una sola parola per descrivere le immagini!
5. Utilizza "#" prima della parola chiave per cercare quella parola senza che essa venga tradotta, nel caso in cui tu abbia, ad esempio, fornito una descrizione personalizzata! (es. Cerca immagine #Toby)
6. Per ottenere tutte le immagini da te caricate fino a questo momento scrivi "Scarica tutte le immagini"
7. Per eliminare le immagini trovate nell'ultima tua ricerca scrivi "Elimina immagini ultima ricerca"
8. Per eliminare tutte le immagini da te caricate fino a questo momento scrivi "Elimina tutte le immagini" 
9. Scrivi "Aiuto" o premi il relativo pulsante alla fine dei miei messaggi se hai bisogno che ti spieghi di nuovo come interagire con me.

Inviami un'immagine per iniziare!
    """
    if update.callback_query:
        query = update.callback_query
        query.answer()
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=help_text, reply_markup=help_button())
        except Exception as e:
            logger.error(f"Failed to edit message: {e}")
            context.bot.send_message(chat_id=chat_id, text=help_text, reply_markup=help_button())
    else:
        chat_id = update.message.chat_id
        context.bot.send_message(chat_id=chat_id, text=help_text, reply_markup=help_button())

def send_start_message(update: Update, context: CallbackContext):
    if not context.user_data.get('batch_started'):
        update.message.reply_text("Inizio del caricamento di tutte le immagini... Questo potrebbe richiedere qualche secondo.")
        context.user_data['batch_started'] = True

def send_summary_message(context: CallbackContext):
    chat_id = context.job.context['chat_id']
    user_data = context.job.context['user_data']
    photo_count = user_data['uploaded_photos_count']

    if photo_count > 0:
        message = "Immagine salvata con successo ed etichettata! Utilizza i comandi di ricerca per recuperarla." if photo_count == 1 else f"{photo_count} immagini salvate con successo ed etichettate! Utilizza i comandi di ricerca per recuperarle."
        context.bot.send_message(chat_id, text=message, reply_markup=help_button())

    user_data['batch_started'] = False
    user_data['uploaded_photos_count'] = 0
    user_data['photo_batch_start_time'] = None

def handle_photo(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data = context.user_data

    if 'photo_batch_start_time' not in user_data or user_data['photo_batch_start_time'] is None:
        user_data['photo_batch_start_time'] = time.time()
        user_data['uploaded_photos_count'] = 0
        update.message.reply_text("Inizio del caricamento di tutte le immagini... Questo potrebbe richiedere qualche secondo.")

    if not update.message.photo:
        update.message.reply_text("Il messaggio non contiene una foto.")
        return

    photo_file = update.message.photo[-1].get_file()
    photo_bytes = photo_file.download_as_bytearray()
    photo_bytes = bytes(photo_bytes) if isinstance(photo_bytes, bytearray) else photo_bytes

    try:
        user_description = update.message.caption.lower() if update.message.caption else ""
        image = vision.Image(content=photo_bytes)

        label_response = vision_client.label_detection(image=image, max_results=50)
        labels = [label.description.lower() for label in label_response.label_annotations]

        object_response = vision_client.object_localization(image=image)
        objects = [obj.name.lower() for obj in object_response.localized_object_annotations]

        text_response = vision_client.text_detection(image=image)
        texts = [text.description.lower() for text in text_response.text_annotations]

        combined_labels = set(labels + objects + texts)
        if user_description:
            combined_labels.update(user_description.split())

        metadata = {'labels': ','.join(combined_labels)}
        file_name = f"{user_id}/{photo_file.file_id}.jpg"

        bucket = storage_client.bucket('photo_chatbot')
        blob = bucket.blob(file_name)
        blob.metadata = metadata
        blob.upload_from_string(photo_bytes, content_type='image/jpeg')

        user_data['uploaded_photos_count'] += 1

        current_jobs = context.job_queue.get_jobs_by_name(f"summary_{user_id}")
        for job in current_jobs:
            job.schedule_removal()

        context.job_queue.run_once(
            check_and_send_summary,
            2,
            context={'chat_id': update.message.chat_id, 'user_data': user_data},
            name=f"summary_{user_id}"
        )

    except Exception as e:
        logger.error(f"Error during image upload: {e}")
        update.message.reply_text("Si è verificato un errore durante il caricamento dell'immagine. Riprova.", reply_markup=help_button())

def check_and_send_summary(context: CallbackContext):
    user_data = context.job.context['user_data']
    chat_id = context.job.context['chat_id']
    current_time = time.time()

    if user_data['photo_batch_start_time'] and (current_time - user_data['photo_batch_start_time']) >= 2:
        send_summary_message(context)

def translate_to_english(text):
    result = translate_client.translate(text, source_language='it', target_language='en')
    return result['translatedText']

def translate_and_synonyms(text, target_language='en'):
    translated_text = translate_to_english(text)
    synonyms = set()
    for synset in wordnet.synsets(translated_text):
        for lemma in synset.lemmas():
            if '_' not in lemma.name() and lemma.name() != translated_text:
                synonyms.add(lemma.name())
    if not synonyms:
        synonyms = {translated_text}
    return list(synonyms)

def fuzzy_search(query, labels, threshold=90):
    matches = process.extract(query, labels, limit=len(labels))
    return [match for match, score in matches if score >= threshold]

def search_images(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    command_text = update.message.text.lower()
    translate = True

    if '#' in command_text:
        query = command_text.split('#')[1].strip()
        translate = False
    else:
        query = command_text.replace('cerca immagine ', '').replace('cerca tutte le immagini ', '').strip()

    found_any = search_images_with_query(update, context, query, translate)

    if not found_any and translate:
        translations_and_synonyms = translate_and_synonyms(query)
        for translated_query in translations_and_synonyms:
            found_any = search_images_with_query(update, context, translated_query, False)
            if found_any:
                break

    if not found_any:
        update.message.reply_text('Nessuna immagine trovata per la tua ricerca. Riprova utilizzando il simbolo "#" prima della parola chiave!', reply_markup=help_button())

def search_images_with_query(update: Update, context: CallbackContext, query: str, translate: bool) -> bool:
    user_id = update.message.from_user.id
    single_search = 'cerca immagine' in update.message.text.lower()
    context.user_data['last_search'] = []

    if translate:
        translated_query = translate_to_english(query)
    else:
        translated_query = query

    blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
    found_any = False
    for blob in blobs:
        blob.reload()
        labels = blob.metadata.get('labels', '').split(',')
        if translated_query.lower() in labels:
            matches = fuzzy_search(translated_query, labels)
            if matches:
                found_any = True
                context.user_data['last_search'].append(blob.name)
                image_bytes = blob.download_as_bytes()
                context.bot.send_photo(chat_id=update.message.chat_id, photo=image_bytes, reply_markup=help_button())
                if single_search:
                    break

    return found_any

def delete_last_search(update: Update, context: CallbackContext):
    try:
        user_id = update.message.from_user.id
        if 'last_search' in context.user_data and context.user_data['last_search']:
            for file_name in context.user_data['last_search']:
                blob = bucket.blob(file_name)
                if blob.exists():
                    blob.delete()
            context.user_data['last_search'] = []
            update.message.reply_text('Immagini dell\'ultima ricerca eliminate con successo.', reply_markup=help_button())
        else:
            update.message.reply_text('Non ci sono immagini da eliminare dalla tua ultima ricerca.', reply_markup=help_button())
    except Exception as e:
        logger.error(f"Errore durante l'eliminazione delle immagini: {str(e)}")
        update.message.reply_text('Si è verificato un errore durante l\'eliminazione delle immagini.')

def delete_all_images(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    count = 0

    try:
        blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
        for blob in blobs:
            blob.delete()
            count += 1

        update.message.reply_text(f'Tutte le tue {count} immagini sono state eliminate con successo.', reply_markup=help_button())

    except Exception as e:
        logger.error(f"Errore durante l'eliminazione delle immagini: {str(e)}")
        update.message.reply_text("Si è verificato un errore durante l'eliminazione delle tue immagini.")

def download_all_images(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    update.message.reply_text("Inizio del download di tutte le immagini... Potrebbe richiedere qualche secondo.")

    try:
        blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
        if blobs:
            for blob in blobs:
                image_bytes = blob.download_as_bytes()
                context.bot.send_photo(chat_id=update.message.chat_id, photo=image_bytes)
            update.message.reply_text("Tutte le immagini sono state scaricate con successo.", reply_markup=help_button())
        else:
            update.message.reply_text("Non ci sono immagini da scaricare.", reply_markup=help_button())
    except Exception as e:
        logger.error(f"Errore durante il download delle immagini: {str(e)}")
        update.message.reply_text("Si è verificato un errore durante il download delle immagini.", reply_markup=help_button())

def error(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def handle_commands(update: Update, context: CallbackContext):
    update.message.reply_text("Azione completata! Usa il pulsante qui sotto per ulteriori aiuti o informazioni.", reply_markup=help_button())

def main() -> None:
    print('Il Bot è partito...')
    updater = Updater(bot_token, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.regex(r'^Start$'), start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(MessageHandler(Filters.regex(r'^Aiuto$'), help_command))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(Filters.regex(r'^Cerca immagine .*$'), search_images))
    dp.add_handler(MessageHandler(Filters.regex(r'^Cerca tutte le immagini .*$'), search_images))
    dp.add_handler(MessageHandler(Filters.regex(r'^Elimina immagini ultima ricerca$'), delete_last_search))
    dp.add_handler(MessageHandler(Filters.regex(r'^Elimina tutte le immagini$'), delete_all_images))
    dp.add_handler(MessageHandler(Filters.regex(r'^Scarica tutte le immagini$'), download_all_images))
    dp.add_handler(CallbackQueryHandler(help_command, pattern='^help$'))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_error_handler(error)
    invalid_command_handler = MessageHandler(Filters.command | Filters.text, handle_invalid_command)
    dp.add_handler(invalid_command_handler)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
