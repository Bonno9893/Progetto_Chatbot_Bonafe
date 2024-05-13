import logging
import time
import nltk
from nltk.corpus import wordnet
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler
from google.cloud import vision, storage, translate_v2
from secret import bot_token

nltk.download('wordnet')

# Configurazione del logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurazione dei client per Google Cloud Vision e Google Cloud Storage
vision_client = vision.ImageAnnotatorClient()
storage_client = storage.Client()
bucket = storage_client.get_bucket('photo_chatbot')
bucket_name = 'photo_chatbot'
translate_client = translate_v2.Client()

# Dizionario per tenere traccia dell'ultimo tempo di upload per ogni utente
last_upload_time = {}

def help_button():
    keyboard = [[InlineKeyboardButton("Aiuto", callback_data='help')]]
    return InlineKeyboardMarkup(keyboard)

def button(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    # Chiama la funzione help_command quando il pulsante di aiuto viene premuto
    if query.data == 'help':
        help_command(update, context)

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters


def handle_invalid_command(update, context):
    update.message.reply_text("""
Comando non valido!
Potresti aver scritto uno dei comandi previsti in modo errato, per esempio senza la maiuscola iniziale...
Prova di nuovo o clicca il pulsante di aiuto, ti invierò di nuovo i comandi da utilizzare nella forma corretta!.""" , reply_markup=help_button())


def start(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Aiuto", callback_data='help')],
    ]
    user_first_name = update.message.from_user.first_name
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(f'Ciao {user_first_name}! Premi il pulsante qui sotto per ottenere aiuto.', reply_markup=reply_markup)


def help_command(update: Update, context: CallbackContext):
    if update.callback_query:
        query = update.callback_query
        query.answer()
        chat_id = query.message.chat_id
        message_id = query.message.message_id
        method = context.bot.edit_message_text
    else:
        chat_id = update.message.chat_id
        message_id = None
        method = context.bot.send_message

    help_text = """
Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Per interagire con me scrivi in chat qui sotto i seguenti comandi:

1. Invia una o più immagini, le conserverò per te!
2. Se invii una sola immagine, puoi scrivere una descrizione composta da una o più parole prima dell'invio. Questa mi aiuterà a trovarla più facilmente!
3. Per cercare un'immagine corrispondente ad una tua descrizione utilizza il comando "Cerca immagine [parola chiave]" (es. Cerca immagine gatto). Utilizza una sola parola per descrivere l'immagine!
4. Per cercare tutte le immagini corrispondenti ad una tua descrizione utilizza il comando "Cerca tutte le immagini [parola chiave]" (es. Cerca tutte le immagini gatto). Utilizza una sola parola per descrivere le immagini!
5. Per ottenere tutte le immagini da te caricate fino a questo momento scrivi "Scarica tutte le immagini"
6. Per eliminare le immagini trovate nell'ultima tua ricerca scrivi "Elimina immagini ultima ricerca"
7. Per eliminare tutte le immagini da te caricate fino a questo momento scrivi "Elimina tutte le immagini" 
8. Scrivi "Aiuto" o premi il relativo pulsante alla fine dei miei messaggi se hai bisogno che ti spieghi di nuovo come interagire con me.

Inviami un'immagine per iniziare!
    """
    context.bot.send_message(chat_id, text=help_text, reply_markup=help_button())


def clear_job_queue(context, name):
    current_jobs = context.job_queue.get_jobs_by_name(name)
    for job in current_jobs:
        job.schedule_removal()


def send_start_message(update: Update, context: CallbackContext):
    if not context.user_data.get('batch_started'):
        update.message.reply_text(
            "Inizio del caricamento di tutte le immagini... Questo potrebbe richiedere un po' di tempo.")
        context.user_data['batch_started'] = True


def send_summary_message(context: CallbackContext):
    chat_id = context.job.context['chat_id']
    user_data = context.job.context['user_data']
    photo_count = user_data['uploaded_photos_count']

    if photo_count > 0:
        if photo_count == 1:
            message = "Immagine salvata con successo ed etichettata!"
        else:
            message = f"{photo_count} immagini salvate con successo ed etichettate!"
        context.bot.send_message(chat_id, text=message,  reply_markup=help_button())

    # Resetta i dati per il prossimo batch di foto
    user_data['batch_started'] = False
    user_data['uploaded_photos_count'] = 0
    user_data['photo_batch_start_time'] = None


def handle_photo(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data = context.user_data

    # Verifica se il job di riepilogo è già stato programmato
    if 'photo_batch_start_time' not in user_data:
        # Inizia un nuovo batch
        user_data['photo_batch_start_time'] = time.time()
        user_data['uploaded_photos_count'] = 0
        update.message.reply_text(
            "Inizio del caricamento di tutte le immagini... Questo potrebbe richiedere un po' di tempo.")

    # Verifica se è presente almeno una foto nell'aggiornamento
    if not update.message.photo:
        update.message.reply_text("Il messaggio non contiene una foto.")
        return

    # Processa la foto ricevuta
    photo_file = update.message.photo[-1].get_file()
    photo_bytes = photo_file.download_as_bytearray()

    if isinstance(photo_bytes, bytearray):
        photo_bytes = bytes(photo_bytes)

    try:
        # Crea il client per Google Cloud Storage e Vision API
        storage_client = storage.Client()
        vision_client = vision.ImageAnnotatorClient()

        # Estrai la descrizione fornita dall'utente se presente
        user_description = update.message.caption.lower() if update.message.caption else ""

        # Analizza l'immagine per ottenere le etichette
        image = vision.Image(content=photo_bytes)
        response = vision_client.label_detection(image=image, max_results=20)
        cloud_vision_labels = [label.description.lower() for label in response.label_annotations]

        # Uniamo le etichette di Cloud Vision e quelle della descrizione dell'utente
        combined_labels = set(cloud_vision_labels)
        if user_description:
            combined_labels.update(user_description.split())

        # Aggiungi le etichette come metadati dell'immagine
        metadata = {'labels': ','.join(combined_labels)}

        # Genera un nome univoco per il file basato su user_id e photo_file_id
        file_name = f"{user_id}/{photo_file.file_id}.jpg"

        # Carica l'immagine su Google Cloud Storage con i relativi metadati
        bucket = storage_client.bucket('photo_chatbot')
        blob = bucket.blob(file_name)
        blob.metadata = metadata
        blob.upload_from_string(photo_bytes, content_type='image/jpeg')

        # Incrementa il conteggio delle immagini caricate con successo
        user_data['uploaded_photos_count'] += 1

    except Exception as e:
        logger.error(f"Error during image upload: {e}")
        update.message.reply_text("Si è verificato un errore durante il caricamento dell'immagine.", reply_markup=help_button())

    # Pianifica il job per inviare il messaggio di riepilogo
    context.job_queue.run_once(
        send_summary_message,
        15,
        context={'chat_id': update.message.chat_id, 'user_data': user_data}
    )


def translate_to_english(text):
    result = translate_client.translate(text, source_language='it', target_language='en')
    return result['translatedText']

def translate_and_synonyms(text, target_language='en'):
    translated_text = translate_to_english(text)
    synonyms = set()
    for synset in wordnet.synsets(translated_text):
        for lemma in synset.lemmas():
            # Filtra solo i sinonimi con una parola
            if '_' not in lemma.name() and lemma.name() != translated_text:
                synonyms.add(lemma.name())
    if not synonyms:
        synonyms = {translated_text}  # Usa la traduzione se non ci sono sinonimi
    print(synonyms)
    return list(synonyms)


# Funzione per la ricerca delle immagini
def search_images(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    command_text = update.message.text.lower()
    query = command_text.replace('cerca immagine ', '').replace('cerca tutte le immagini ', '').strip()

    # Prima ricerca utilizzando la query originale
    found_any = search_images_with_query(update, context, query)

    # Se non troviamo nulla con la query originale, proviamo con i sinonimi
    if not found_any:
        translations_and_synonyms = translate_and_synonyms(query)
        for translated_query in translations_and_synonyms:
            found_any = search_images_with_query(update, context, translated_query)
            if found_any:
                break

    if not found_any:
        update.message.reply_text('Nessuna immagine trovata per la tua ricerca.', reply_markup=help_button())


def search_images_with_query(update: Update, context: CallbackContext, query: str) -> bool:
    user_id = update.message.from_user.id
    single_search = 'cerca immagine' in update.message.text.lower()
    context.user_data['last_search'] = []  # Prepara la lista per tenere traccia dell'ultima ricerca

    translated_query = translate_to_english(query)
    print(translated_query)

    blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
    found_any = False
    for blob in blobs:
        blob.reload()
        labels = blob.metadata.get('labels', '').split(',')
        if translated_query.lower() in labels:
            found_any = True
            context.user_data['last_search'].append(blob.name)
            image_bytes = blob.download_as_bytes()
            context.bot.send_photo(chat_id=update.message.chat_id, photo=image_bytes, reply_markup=help_button())
            if single_search:
                break

    return found_any


def delete_last_search(update: Update, context: CallbackContext):
    logger.info("Comando di eliminazione ricevuto")
    try:
        user_id = update.message.from_user.id
        if 'last_search' in context.user_data and context.user_data['last_search']:
            logger.info(f"Eliminazione delle immagini: {context.user_data['last_search']}")
            for file_name in context.user_data['last_search']:
                blob = bucket.blob(file_name)
                if blob.exists():
                    blob.delete()
            context.user_data['last_search'] = []  # Pulisci la lista dopo l'eliminazione
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
        # Crea un elenco di tutti i blob nel bucket per questo utente
        blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
        for blob in blobs:
            blob.delete()  # Elimina il file
            count += 1

        update.message.reply_text(f'Tutte le tue {count} immagini sono state eliminate con successo.', reply_markup=help_button())

    except Exception as e:
        logger.error(f"Errore durante l'eliminazione delle immagini: {str(e)}")
        update.message.reply_text("Si è verificato un errore durante l'eliminazione delle tue immagini.")


def download_all_images(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    update.message.reply_text("Inizio del download di tutte le immagini... Questo potrebbe richiedere un po' di tempo.")

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
    """Logga gli errori causati dagli aggiornamenti."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def handle_commands(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Azione completata! Usa il pulsante qui sotto per ulteriori aiuti o informazioni.",
        reply_markup=help_button()
    )

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

    invalid_command_handler = MessageHandler(Filters.command | Filters.text, handle_invalid_command)
    dp.add_handler(invalid_command_handler)

    # Registrazione del gestore di errori
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()