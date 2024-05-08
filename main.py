# PROGETTO PHOTO CHATBOT

import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, Filters
from google.cloud import storage
from secret import bot_token

# Configurazione del logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# Imposta le credenziali del client di Google Cloud Storage
# Assicurati di impostare questa variabile d'ambiente nel tuo ambiente di sviluppo
# export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials/my-project-credentials.json
# Creazione del client di Google Cloud Storage
storage_client = storage.Client()

def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Ciao, inviami un\'immagine!')

def help_command(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Ciao, mi presento, sono Photo Chatbot! Il mio compito è di memorizzare le immagini inviate dagli utenti e di recuperarle tramite la loro descrizione. Inviami un\'immagine per iniziare.')

def echo(update: Update, context: CallbackContext) -> None:
    update.message.reply_text(update.message.text)

def handle_photo(update: Update, context: CallbackContext) -> None:
    user = update.message.from_user
    update.message.reply_text(f"Immagine ricevuta! Grazie, {user.first_name}.")
    client = storage.Client.from_service_account_json('photo-chatbot-1-16d5d9d04aaa.json')
    #bucket = client.create_bucket('upload-mamei-1')
    bucket = client.bucket('photo_chatbot')
    source_file_name = 'test.jpg'
    destination_blob_name = source_file_name
    blob = bucket.blob(f"images/{update.message.photo[-1].file_id}.jpg")
    blob.upload_from_filename(update.message.photo[-1].get_file().download_as_bytearray())
    print("File {} uploaded to {}.".format(source_file_name, destination_blob_name))

def error(update, context):
    """Logga gli errori causati dagli aggiornamenti."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)

def main() -> None:
    updater = Updater(bot_token, use_context=True)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, echo))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))

    # Registrazione del gestore di errori
    dp.add_error_handler(error)

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
