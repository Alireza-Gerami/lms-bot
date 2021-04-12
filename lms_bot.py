import logging
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    ConversationHandler,
)
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from decouple import config
from scraper import get_events, sign_in

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)

TOKEN = config('TOKEN')
PORT = int(config('PORT'))
HEROKU_APP_NAME = config('HEROKU_APP_NAME')
logger = logging.getLogger(__name__)

LOGIN, USERNAME, PASSWORD, EVENTS = range(4)


def start(update, context):
    reply_keyboard = [
        ['ورود به سامانه'],
    ]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    update.message.reply_text(
        f' سلام {update.message.chat.first_name}'
        '\nبه ربات LMS دانشگاه خوش آمدی'
        '\nبرای دیدن آخرین رویدادهای خودت باید وارد سامانه بشی. (نام کاربری و پسورد هرگز ذخیره نمی شود)'
        '\nاگر منصرف شدی میتونی /cancel رو بفرستی.',
        reply_markup=markup
    )
    return USERNAME


def username(update, context):
    update.message.reply_text(
        'لطفا نام کاربری را وارد کن',
        reply_markup=ReplyKeyboardRemove(),
    )
    return PASSWORD


def password(update, context):
    context.user_data['username'] = update.message.text
    update.message.reply_text(
        'لطفا رمز ورود را وارد کن',
        reply_markup=ReplyKeyboardRemove(),
    )
    return LOGIN


def login(update, context):
    context.user_data['password'] = update.message.text
    session = sign_in(context.user_data['username'], context.user_data["password"])
    if session:
        reply_keyboard = [['نمایش رویدادها']]
        msg = 'با موفقیت وارد شدید.'
        context.user_data['session'] = session
    else:
        reply_keyboard = [['ورود به سامانه']]
        msg = 'نام کاربری یا رمز ورود نامعتبر است.'
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    update.message.reply_text(
        msg,
        reply_markup=markup,
    )
    return EVENTS if session else USERNAME


def events(update, context):
    events_list = get_events(context.user_data['session'])
    msg = ''
    if events_list:
        if len(events_list) == 0:
            msg = 'برو حال کن هیچ رویداد نزدیکی نداری.'
        else:
            for event in events_list:
                msg += f'نام درس:  {event["lesson"]}\nعنوان تمرین:   {event["name"]}\nمهلت تا:   {event["deadline"]}\nوضعیت: {event["status"]}\n\n'
    else:
        msg = 'لطفا بعدا تلاش کنید.'
    update.message.reply_text(msg,
                              reply_markup=ReplyKeyboardRemove(),
                              )
    return ConversationHandler.END


def cancel(update, context):
    update.message.reply_text(
        'به امید دیدار'
        '\nبرای شروع دوباره /start رو بفرست.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


def error(update, context):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def main():
    updater = Updater(TOKEN, use_context=True)

    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            USERNAME: [MessageHandler(Filters.regex('^ورود به سامانه'), username)],
            PASSWORD: [MessageHandler(Filters.text & ~Filters.command, password)],
            LOGIN: [MessageHandler(Filters.text & ~Filters.command, login)],
            EVENTS: [MessageHandler(Filters.regex('^نمایش رویدادها'), events)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    dispatcher.add_handler(conv_handler)

    dispatcher.add_error_handler(error)

    updater.start_webhook(listen='0.0.0.0',
                          port=PORT,
                          url_path=TOKEN,
                          webhook_url=f'https://{HEROKU_APP_NAME}.herokuapp.com/' + TOKEN)

    updater.idle()


if __name__ == '__main__':
    main()
