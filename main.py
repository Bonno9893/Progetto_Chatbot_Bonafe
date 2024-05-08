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

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Ciao, inviami un\'immagine o chiedimi di cercare immagini basate su descrizioni!')

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        'Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Inviami un\'immagine per iniziare.')

def handle_photo(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    photo_file = update.message.photo[-1].get_file()
    photo_bytes = photo_file.download_as_bytearray()
    photo_bytes = bytes(photo_bytes)  # Conversione a bytes

    # Analizza l'immagine per ottenere le etichette
    image = vision.Image(content=photo_bytes)
    response = vision_client.label_detection(image=image)
    labels = [label.description.lower() for label in response.label_annotations]  # Converti le etichette in minuscolo

    # Genera un nome univoco per il file basato su user_id e photo_file_id
    photo_file_id = photo_file.file_id
    file_name = f'{user_id}/{photo_file_id}.jpg'

    # Carica l'immagine su Google Cloud Storage
    blob = bucket.blob(file_name)
    blob.metadata = {'labels': ','.join(labels)}  # Salva le etichette come metadati
    blob.upload_from_string(photo_bytes, content_type='image/jpeg')

    # Conferma all'utente che l'immagine è stata salvata
    update.message.reply_text('Immagine salvata con successo e etichettata!')

def search_images(update: Update, context: CallbackContext) -> None:
    query = update.message.text.lower().replace('cerca immagine', '').strip()
    user_id = update.message.from_user.id
    found_images = []

    # Scansiona tutte le immagini salvate per questo utente
    blobs = list(bucket.list_blobs(prefix=f'{user_id}/'))
    for blob in blobs:
        blob.reload()  # Ricarica i metadati del blob
        labels = blob.metadata.get('labels', '').lower()  # Converti le etichette in minuscolo
        if query in labels:
            found_images.append(blob.public_url)

    if found_images:
        for img_url in found_images:
            update.message.reply_photo(photo=img_url)
    else:
        update.message.reply_text('Nessuna immagine trovata per la tua ricerca.')

def error(update, context):
    """Logga gli errori causati dagli aggiornamenti."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main():
    """Start the bot."""
    updater = Updater(bot_token, use_context=True)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, search_images))

    # Avvia il bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()

