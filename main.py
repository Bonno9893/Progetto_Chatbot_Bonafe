import logging
import time
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from google.cloud import vision, storage, translate_v2
from secret import bot_token

# Configurazione del logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurazione dei client per Google Cloud Vision, Google Cloud Storage e Google Cloud Translation
vision_client = vision.ImageAnnotatorClient()
storage_client = storage.Client()
translate_client = translate_v2.Client()
bucket = storage_client.get_bucket('photo_chatbot')

# Dizionario dei messaggi multilingua
messaggi = {
    'start': {
        'en': "Hello, send me an image to start!",
        'it': "Ciao, inviami un'immagine per iniziare!"
    },
    'help': {
        'en': """Hi, let me introduce myself, I am Photo Chatbot! My job is to store images submitted by users and retrieve them via their description. To interact with me use the following commands:

1. Send one or more images, I will store them for you!
2. \"Search image *\" to search for an image based on your description (e.g., Search cat image)
3. \"Search all images *\" to search for all images matching that description (e.g., Search all cat images)
4. \"Download all images\" to get all images you have uploaded so far
5. \"Delete last search images\" to delete the images found in your last search
6. \"Delete all images\" to delete all images you uploaded up to this moment
7. \"Start\" to get started!
8. \"Help\" if you need me to explain again how to interact with me.

Send me an image to get started!""",
        'it': """Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Per interagire con me utilizza i seguenti comandi:

1. Invia una o più immagini, le conserverò per te!
2. \"Cerca immagine *\" per cercare un'immagine in base alla tua descrizione (es., Cerca immagine gatto)
3. \"Cerca tutte le immagini *\" per cercare tutte le immagini corrispondenti a quella descrizione (es., Cerca tutte le immagini gatto)
4. \"Scarica tutte le immagini\" per ottenere tutte le immagini da te caricate fino a questo momento
5. \"Elimina immagini ultima ricerca\" per eliminare le immagini trovate nell'ultima tua ricerca
6. \"Elimina tutte le immagini\" per eliminare tutte le foto da te caricate fino a questo momento
7. \"Start\" per iniziare!
8. \"Aiuto\" se hai bisogno che ti spieghi di nuovo come interagire con me.

Inviami un'immagine per iniziare!"""
    },
    'no_images_found': {
        'en': "No images found for your search.",
        'it': "Nessuna immagine trovata per la tua ricerca."
    },
    'images_deleted': {
        'en': "Images from the last search were successfully deleted.",
        'it': "Le immagini dell'ultima ricerca sono state eliminate con successo."
    },
    'no_images_to_delete': {
        'en': "There are no images to delete from your last search.",
        'it': "Non ci sono immagini da eliminare dalla tua ultima ricerca."
    },
    'error_deleting_images': {
        'en': "An error occurred during the deletion of images.",
        'it': "Si è verificato un errore durante l'eliminazione delle immagini."
    },
    'all_images_deleted': {
        'en': "All your images have been successfully deleted.",
        'it': "Tutte le tue immagini sono state eliminate con successo."
    },
    'download_started': {
        'en': "Starting the download of all your images... This may take some time.",
        'it': "Inizio del download di tutte le tue immagini... Questo potrebbe richiedere un po' di tempo."
    },
    'all_images_downloaded': {
        'en': "All images have been downloaded successfully.",
        'it': "Tutte le immagini sono state scaricate con successo."
    },
    'error_during_download': {
        'en': "An error occurred during the download of images.",
        'it': "Si è verificato un errore durante il download delle immagini."
    },
    'uploading_started': {
        'en': "Starting the upload of all your images... This may take some time.",
        'it': "Inizio del caricamento di tutte le tue immagini... Questo potrebbe richiedere un po' di tempo."
    },
    'upload_successful': {
        'en': "Image successfully uploaded and labeled!",
        'it': "Immagine caricata con successo ed etichettata!"
    },
    'error_uploading': {
        'en': "An error occurred during the upload of the image.",
        'it': "Si è verificato un errore durante il caricamento dell'immagine."
    }
}


def ask_language(update: Update, context: CallbackContext):
    keyboard = [['English', 'Italiano']]  # Aggiungi altre lingue qui se necessario
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text('Please choose your language / Per favore, scegli la tua lingua:', reply_markup=reply_markup)

def set_language(update: Update, context: CallbackContext):
    chosen_language = update.message.text
    context.user_data['lang'] = 'en' if chosen_language == 'English' else 'it'
    start(update, context)  # Invia il messaggio di benvenuto nella lingua scelta

# Determinazione della lingua dell'utente
def get_user_lang(update: Update, context: CallbackContext):
    return context.user_data.get('lang', 'en')




def translate_to_english(text):
    if translate_client.detect_language(text)['language'] == 'en':
        return text
    result = translate_client.translate(text, target_language='en')
    return result['translatedText']


# Funzione per iniziare la conversazione e impostare la lingua
def start(update: Update, context: CallbackContext):
    user_lang = get_user_lang(update, context)
    update.message.reply_text(messaggi['start'][user_lang])


# Funzione di aiuto che fornisce informazioni sull'utilizzo del bot
def help_command(update: Update, context: CallbackContext):
    user_lang = get_user_lang(update, context)
    update.message.reply_text(messaggi['help'][user_lang])


# Gestione delle foto ricevute


def clear_job_queue(context, name):
    # Ottieni tutti i job dal JobQueue
    current_jobs = context.job_queue.get_jobs_by_name(name)
    for job in current_jobs:
        # Pianifica la rimozione di ogni job
        job.schedule_removal()

def send_summary_message(context: CallbackContext):
    job_context = context.job.context
    chat_id = job_context['chat_id']
    user_data = job_context['user_data']
    user_lang = user_data.get('lang', 'en')  # Assicurati che 'lang' sia memorizzato in 'user_data'

    photo_count = user_data['uploaded_photos_count']
    if photo_count > 0:
        if photo_count == 1:
            message = messaggi['one_image_uploaded'][user_lang]  # Assicurati di avere questo messaggio nel dizionario
        else:
            message = f"{photo_count} " + messaggi['images_uploaded'][user_lang]  # Assicurati di avere questo messaggio nel dizionario
        context.bot.send_message(chat_id, text=message)

    # Resetta i dati per il prossimo batch di foto
    user_data['batch_started'] = False
    user_data['uploaded_photos_count'] = 0
    user_data['photo_batch_start_time'] = None

def handle_photo(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data = context.user_data
    user_lang = user_data.get('lang', 'en')  # Ottieni la lingua dell'utente, default a inglese

    # Verifica se il job di riepilogo è già stato programmato
    if 'photo_batch_start_time' not in user_data:
        # Inizia un nuovo batch
        user_data['photo_batch_start_time'] = time.time()
        user_data['uploaded_photos_count'] = 0
        update.message.reply_text(messaggi['download_started'][user_lang])  # Messaggio di inizio upload in lingua dell'utente

    # Processa la foto ricevuta
    photo_file = update.message.photo[-1].get_file()
    photo_bytes = photo_file.download_as_bytearray()
    if isinstance(photo_bytes, bytearray):
        photo_bytes = bytes(photo_bytes)

    try:
        # Crea il client per Google Cloud Storage e Vision API
        storage_client = storage.Client()
        vision_client = vision.ImageAnnotatorClient()

        # Analizza l'immagine per ottenere le etichette
        image = vision.Image(content=photo_bytes)
        response = vision_client.label_detection(image=image)
        labels = [label.description.lower() for label in response.label_annotations]

        # Genera un nome univoco per il file basato su user_id e photo_file_id
        file_name = f"{user_id}/{photo_file.file_id}.jpg"

        # Carica l'immagine su Google Cloud Storage
        bucket = storage_client.bucket('photo_chatbot')
        blob = bucket.blob(file_name)
        blob.metadata = {'labels': ','.join(labels)}
        blob.upload_from_string(photo_bytes, content_type='image/jpeg')

        # Incrementa il conteggio delle immagini caricate con successo
        user_data['uploaded_photos_count'] += 1

    except Exception as e:
        logger.error(f"Error during image upload: {e}")
        update.message.reply_text(messaggi['error_during_upload'][user_lang])  # Messaggio di errore in lingua dell'utente

    # Pianifica il job per inviare il messaggio di riepilogo
    context.job_queue.run_once(
        send_summary_message,
        15,
        context={'chat_id': update.message.chat_id, 'user_data': user_data}
    )


# Ricerca di immagini basata su descrizione
def search_images(update: Update, context: CallbackContext):
    user_lang = get_user_lang(update, context)  # Assicurati che questa funzione restituisca la lingua dell'utente
    user_id = update.message.from_user.id
    command_text = update.message.text.lower()
    # Ottieni la parte della query dopo il comando
    if command_text.startswith("search image"):
        query = command_text.replace('search image', '').strip()
    else:
        query = command_text.replace('search all images', '').strip()

    # Traduci la query in inglese se necessario
    translated_query = translate_to_english(query)

    # Determina se la ricerca è per una singola immagine o per tutte
    single = 'search image' in command_text

    context.user_data['last_search'] = []  # Prepara la lista per tenere traccia dell'ultima ricerca
    blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
    found_any = False
    for blob in blobs:
        blob.reload()
        labels = blob.metadata.get('labels', '').split(',')
        if translated_query in labels:
            found_any = True
            context.user_data['last_search'].append(blob.name)
            image_bytes = blob.download_as_bytes()
            context.bot.send_photo(chat_id=update.message.chat_id, photo=image_bytes)
            if single:
                break  # Esci dopo aver trovato e inviato la prima immagine corrispondente

    if not found_any:
        update.message.reply_text(messaggi['no_image_found'][user_lang])  # Usa il messaggio multilingua



# Eliminazione dell'ultima ricerca di immagini
def delete_last_search(update: Update, context: CallbackContext):
    user_lang = get_user_lang(update, context)
    try:
        if 'last_search' in context.user_data:
            for blob_name in context.user_data['last_search']:
                blob = bucket.blob(blob_name)
                blob.delete()
            context.user_data.pop('last_search', None)
            update.message.reply_text(messaggi['images_deleted'][user_lang])
        else:
            update.message.reply_text(messaggi['no_images_to_delete'][user_lang])
    except Exception as e:
        logger.error(f"Error during image deletion: {str(e)}")
        update.message.reply_text(messaggi['error_deleting_images'][user_lang])


# Eliminazione di tutte le immagini caricate dall'utente
def delete_all_images(update: Update, context: CallbackContext):
    user_lang = get_user_lang(update, context)
    user_id = update.message.from_user.id
    blobs = list(bucket.list_blobs(prefix=f"{user_id}/"))
    for blob in blobs:
        blob.delete()
    update.message.reply_text(messaggi['all_images_deleted'][user_lang])


# Download di tutte le immagini
def download_all_images(update: Update, context: CallbackContext):
    user_lang = get_user_lang(update, context)
    user_id = update.message.from_user.id
    update.message.reply_text(messaggi['download_started'][user_lang])
    blobs = list(bucket.list_blobs(prefix=f"{user_id}/"))
    for blob in blobs:
        image_bytes = blob.download_as_bytes()
        update.message.reply_photo(photo=image_bytes)
    update.message.reply_text(messaggi['all_images_downloaded'][user_lang])


# Funzione per gestire gli errori
def error(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


# Funzione principale per avviare il bot
def main():
    updater = Updater(bot_token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(Filters.regex('^(English|Italiano)$'), set_language))
    dp.add_handler(CommandHandler('start', ask_language))
    #dp.add_handler(MessageHandler(Filters.regex(r'^Start$'), start))
    dp.add_handler(MessageHandler(Filters.regex(r'^Help$'), help_command))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(Filters.regex(r'^Search image.*'), search_images))
    dp.add_handler(MessageHandler(Filters.regex(r'^Search all images.*'), search_images))
    dp.add_handler(MessageHandler(Filters.regex(r'^Delete last search'), delete_last_search))
    dp.add_handler(MessageHandler(Filters.regex(r'^Delete all images'), delete_all_images))
    dp.add_handler(MessageHandler(Filters.regex(r'^Download all images'), download_all_images))
    dp.add_error_handler(error)



    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
