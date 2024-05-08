# PROGETTO PHOTO CHATBOT

import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, Filters
from secret import bot_token
from google.cloud import storage
from google.cloud import vision
from typing import Dict

# Configurazione del logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Inizializza il client di Google Cloud Storage
storage_client = storage.Client()
bucket = storage_client.get_bucket('photo_chatbot')


# Inizializza il client di Google Cloud Vision
vision_client = vision.ImageAnnotatorClient()


def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Ciao, inviami un\'immagine!')


def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(
        'Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Inviami un\'immagine per iniziare.')


def handle_photo(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    photo_file = update.message.photo[-1].get_file()
    photo_bytes = photo_file.download_as_bytearray()

    # Converti bytearray in bytes
    photo_bytes = bytes(photo_bytes)

    # Analizza l'immagine per ottenere le etichette
    image = vision.Image(content=photo_bytes)
    response = vision_client.label_detection(image=image)
    labels = [label.description for label in response.label_annotations]

    # Genera un nome univoco per il file basato su user_id e photo_file_id
    photo_file_id = photo_file.file_id
    file_name = f'{user_id}/{photo_file_id}.jpg'

    # Carica l'immagine su Google Cloud Storage
    blob = bucket.blob(file_name)
    blob.metadata = {'labels': ','.join(labels)}  # Salva le etichette come metadati
    blob.upload_from_string(photo_bytes, content_type='image/jpeg')

    # Conferma all'utente che l'immagine è stata salvata
    update.message.reply_text('Immagine salvata con successo con etichette.')




def search_images(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    search_query = update.message.text.lower()

    if "cerca immagine" not in search_query:
        update.message.reply_text("Per favore, inserisci una query di ricerca valida. Ad esempio: 'Cerca immagine cane'.")
        return

    search_query = search_query.replace("cerca immagine", "").strip()

    if user_id not in user_images:
        update.message.reply_text("Nessuna immagine trovata per questo utente.")
        return

    found_images = []
    for photo_id, image_content in user_images[user_id].items():
        description = generate_description(image_content)
        if search_query in description:
            found_images.append(photo_id)

    if found_images:
        # Restituisci le immagini trovate all'utente
        for photo_id in found_images:
            context.bot.send_photo(chat_id=update.message.chat_id, photo=photo_id)
    else:
        update.message.reply_text("Nessuna immagine trovata per questa descrizione.")





def generate_description(image_content: bytes) -> str:
    # Analizza il contenuto dell'immagine utilizzando Google Cloud Vision
    image = vision.Image(content=image_content)
    response = vision_client.label_detection(image=image)

    # Estrai le etichette rilevate dall'immagine
    labels = [label.description.lower() for label in response.label_annotations]

    # Genera una descrizione basata sulle etichette rilevate
    return ", ".join(labels)


def error(update, context):
    """Logga gli errori causati dagli aggiornamenti."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main() -> None:
    updater = Updater(bot_token, use_context=True)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, search_images))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))

    # Registrazione del gestore di errori
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()