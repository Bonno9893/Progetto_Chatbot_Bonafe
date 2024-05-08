import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from google.cloud import vision, storage
from secret import bot_token

# Configurazione del logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configurazione dei client per Google Cloud Vision e Google Cloud Storage
vision_client = vision.ImageAnnotatorClient()
storage_client = storage.Client()
bucket = storage_client.get_bucket('photo_chatbot')
bucket_name = 'photo_chatbot'

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Ciao, inviami un\'immagine!')

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        'Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Inviami un\'immagine per iniziare.')

def handle_photo(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.message.from_user.id
        photo_file = update.message.photo[-1].get_file()
        photo_bytes = photo_file.download_as_bytearray()
        photo_bytes = bytes(photo_bytes)  # Conversione a bytes

        # Crea il client per Google Cloud Storage utilizzando le credenziali dal file JSON
        client = storage.Client.from_service_account_json('photo-chatbot-1-16d5d9d04aaa.json')

        # Analizza l'immagine per ottenere le etichette
        image = vision.Image(content=photo_bytes)
        response = vision_client.label_detection(image=image)
        labels = [label.description.lower() for label in response.label_annotations]  # Converti le etichette in minuscolo

        # Genera un nome univoco per il file basato su user_id e photo_file_id
        file_name = f'{user_id}/{photo_file.file_id}.jpg'

        # Carica l'immagine su Google Cloud Storage
        bucket = client.bucket('photo_chatbot')  # Seleziona il bucket corretto
        blob = bucket.blob(file_name)
        blob.metadata = {'labels': ','.join(labels)}  # Salva le etichette come metadati
        blob.upload_from_string(photo_bytes, content_type='image/jpeg')

        # Conferma all'utente che l'immagine è stata salvata
        update.message.reply_text('Immagine salvata con successo e etichettata!')
    except Exception as e:
        logger.error(f"Errore durante il caricamento dell'immagine: {str(e)}")
        update.message.reply_text('Si è verificato un errore durante il caricamento dell\'immagine.')


def search_single_image(update: Update, context: CallbackContext) -> None:
    search_images(update, context, single=True)

def search_all_images(update: Update, context: CallbackContext) -> None:
    search_images(update, context, single=False)

def search_images(update: Update, context: CallbackContext, single=True):
    try:
        user_id = update.message.from_user.id
        command_text = update.message.text.lower()
        if "cerca tutte le immagini" in command_text:
            query = command_text.replace('cerca tutte le immagini', '').strip()
            single = False
        else:
            query = command_text.replace('cerca immagine', '').strip()
            single = True

        # Scansiona tutte le immagini salvate per questo utente
        blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
        found_any = False  # Flag per verificare se abbiamo trovato almeno una immagine
        for blob in blobs:
            blob.reload()  # Ricarica i metadati del blob
            labels = blob.metadata.get('labels', '').lower()  # Converti le etichette in minuscolo
            if query in labels:
                found_any = True
                image_bytes = blob.download_as_bytes()
                context.bot.send_photo(chat_id=update.message.chat_id, photo=image_bytes)
                if single:
                    return  # Se è richiesta solo una foto, interrompe dopo il primo match

        if not found_any:
            update.message.reply_text('Nessuna immagine trovata per la tua ricerca.')
    except Exception as e:
        logger.error(f"Errore durante la ricerca delle immagini: {str(e)}")
        update.message.reply_text('Si è verificato un errore durante la ricerca delle immagini.')




def error(update, context):
    """Logga gli errori causati dagli aggiornamenti."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main() -> None:
    print('Il Bot è partito...')
    updater = Updater(bot_token, use_context=True)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(CommandHandler("cerca_immagine", search_single_image))
    dp.add_handler(CommandHandler("cerca_tutte_le_immagini", search_all_images))
    dp.add_handler(MessageHandler(Filters.text & Filters.regex(r'(?i)^cerca immagine.*'), search_single_image))
    dp.add_handler(MessageHandler(Filters.text & Filters.regex(r'(?i)^cerca tutte le immagini.*'), search_all_images))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))

    # Registrazione del gestore di errori
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

