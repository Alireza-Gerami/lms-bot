import logging
import requests
import redis
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext)
from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove, ChatAction, Update, ForceReply)
from decouple import config
from scraper import (get_events, sign_in, get_student_courses, get_course_activities, session_is_connected)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)

TOKEN = config('TOKEN')
PORT = int(config('PORT'))
HEROKU_APP_NAME = config('HEROKU_APP_NAME')
DB_HOST = config('DB_HOST')
DB_PORT = int(config('DB_PORT'))
DB_PASSWORD = config('DB_PASSWORD')
ADMIN_CHAT_ID = int(config('ADMIN_CHAT_ID'))

# Redis db to save chat_id
db = redis.Redis(host=DB_HOST, port=DB_PORT, password=DB_PASSWORD)
logger = logging.getLogger(__name__)

# Conversation handler states
LOGIN, USERNAME, PASSWORD, MENU, CONFIRM_EXIT, BROADCAST = range(6)

# Reply keyboards
reply_keyboard_login = [['ورود به سامانه']]
reply_keyboard_menu_first = [['نمایش رویدادهای نزدیک'], ['فعال کردن اطلاع رسانی فعالیت جدید'], ['خروج']]
reply_keyboard_menu_second = [['نمایش رویدادهای نزدیک'], ['غیر فعال کردن اطلاع رسانی فعالیت جدید'], ['خروج']]

# General messages
restart_msg = 'لطفا دوباره با ارسال /start شروع کن.'
goodbye_msg = 'به امید دیدار' \
              '\nبرای شروع دوباره /start را بفرست.'


def start(update: Update, context: CallbackContext):
    """ Start bot with /start command """
    chat_id = update.message.chat_id
    user_name = update.message.from_user.username
    db.set(user_name, chat_id)
    context.user_data['started'] = True
    markup = ReplyKeyboardMarkup(reply_keyboard_login, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text(
        f' سلام {update.message.chat.first_name}'
        '\nبه ربات LMS دانشگاه خوش آمدی'
        '\nبرای ادامه کار باید وارد سامانه بشی. (نام کاربری و پسورد هرگز ذخیره نمی شود)'
        '\nاگر منصرف شدی میتونی /exit رو بفرستی.',
        reply_markup=markup
    )
    return USERNAME


def username(update: Update, _: CallbackContext):
    """ Getting login information """
    update.message.reply_text(
        'لطفا نام کاربری را وارد کن', reply_markup=ForceReply())
    return PASSWORD


def password(update: Update, context: CallbackContext):
    """ Getting login information """
    context.user_data['username'] = update.message.text
    update.message.reply_text(
        'لطفا رمز ورود را وارد کن', reply_markup=ForceReply())
    return LOGIN


def login(update: Update, context: CallbackContext):
    """ Login to lms and set session """
    chat_id = update.message.chat_id
    context.user_data['password'] = update.message.text
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    session, reply_msg = sign_in(context.user_data['username'], context.user_data["password"])
    if session:
        chat_id = update.message.chat_id
        if job_if_exists(str(chat_id), context):
            reply_keyboard = reply_keyboard_menu_second
        else:
            reply_keyboard = reply_keyboard_menu_first
        context.user_data['session'] = session
    else:
        reply_keyboard = reply_keyboard_login
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    update.message.reply_text(
        reply_msg,
        reply_markup=markup,
    )
    return MENU if session else USERNAME


def events(update: Update, context: CallbackContext):
    """ Show upcoming events """
    context.bot.sendChatAction(chat_id=update.message.chat_id, action=ChatAction.TYPING)
    if not session_exists(context):
        reply_msg = restart_msg
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not session_is_connected(context.user_data['session']):
        session, msg = sign_in(context.user_data['username'], context.user_data["password"])
        context.user_data['session'] = session
    events_list, reply_msg = get_events(context.user_data['session'])
    if events_list:
        if len(events_list) == 0:
            reply_msg = 'برو حال کن هیچ رویداد نزدیکی نداری.'
        else:
            for event in events_list:
                reply_msg += f'نام درس:   {event["lesson"]}\nعنوان فعالیت:   {event["name"]}\nمهلت تا:   {event["deadline"]}\nوضعیت:   {event["status"]}\n\n'
    update.message.reply_text(reply_msg)
    return MENU


def session_exists(context: CallbackContext):
    """ Check user is login """
    if 'session' in context.user_data:
        return True
    return False


def job_if_exists(name: str, context: CallbackContext, remove=False):
    """ Check job is exists in bot job_queue """
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    if remove:
        for job in current_jobs:
            job.schedule_removal()
    return True


def alert(context: CallbackContext):
    """ Send notification if new activity added """
    job = context.job
    if not session_is_connected(job.context.user_data['session']):
        session, msg = sign_in(job.context.user_data['username'], job.context.user_data["password"])
        job.context.user_data['session'] = session
    courses = job.context.user_data['courses']
    for course in courses:
        activities, msg = get_course_activities(job.context.user_data['session'], course['id'])
        last_activities_id = job.context.user_data[course['id']]
        if len(activities) != len(last_activities_id):
            new_activities_id = []
            reply_msg = '\n\U0001F514  فعالیت های جدیدی اضافه شد \U0001F514\n\n'
            for activity in activities:
                if activity['id'] not in last_activities_id:
                    reply_msg += f'نام درس:  {course["name"]}\nفعالیت های جدید:   '
                    status = "مشاهده شده است. \U00002705" if activity[
                                                                 "status"] == "0" else "مشاهده نشده است. \U0000274C"
                    reply_msg += f'\n        عنوان فعالیت:   {activity["name"]}\n        وضعیت:   {status}\n\n'
                    new_activities_id.append(activity['id'])
            last_activities_id.extend(new_activities_id)
            job.context.user_data[course['id']] = last_activities_id
            context.bot.send_message(job.context.user_data['chat_id'], reply_msg)


def set_alert(update: Update, context: CallbackContext):
    """ Set notification of new activities """
    chat_id = update.message.chat_id
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    markup = None
    if not session_exists(context):
        reply_msg = restart_msg
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not job_if_exists(str(chat_id), context):
        reply_msg = 'اطلاع رسانی فعالیت جدید فعال شد.'
        if not session_is_connected(context.user_data['session']):
            session, msg = sign_in(context.user_data['username'], context.user_data["password"])
            context.user_data['session'] = session
        courses, msg = get_student_courses(context.user_data['session'])
        if courses:
            context.user_data['courses'] = courses
            for course in courses:
                activities, msg = get_course_activities(context.user_data['session'], course['id'])
                if activities:
                    context.user_data[course['id']] = [activity['id'] for activity in activities]
                else:
                    reply_msg = msg
            if reply_msg != msg:
                reply_keyboard = reply_keyboard_menu_second
                markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
                context.user_data['alert'] = True
                context.user_data['chat_id'] = chat_id
                context.job_queue.run_repeating(alert, context=context, name=str(chat_id), interval=2 * 60 * 60)
        else:
            reply_msg = msg
    else:
        reply_msg = 'اطلاع رسانی فعال است.'
    if markup:
        update.message.reply_text(reply_msg, reply_markup=markup)
    else:
        update.message.reply_text(reply_msg)
    return MENU


def unset_alert(update: Update, context: CallbackContext):
    """ Unset notification of new activities """
    chat_id = update.message.chat_id
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    markup = None
    if not session_exists(context):
        reply_msg = restart_msg
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if job_if_exists(str(chat_id), context, remove=True):
        reply_keyboard = reply_keyboard_menu_first
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        reply_msg = 'اطلاع رسانی فعالیت جدید غیر فعال شد.'
        context.user_data['alert'] = False
    else:
        reply_msg = 'اطلاع رسانی غیر فعال است.'
    if markup:
        update.message.reply_text(reply_msg, reply_markup=markup)
    else:
        update.message.reply_text(reply_msg)
    return MENU


def confirm_exit(update: Update, context: CallbackContext):
    """ Confirm exit if user sets alert """
    if update.message.text == 'آره':
        chat_id = update.message.chat_id
        job_if_exists(str(chat_id), context, remove=True)
        context.user_data.clear()
        update.message.reply_text(goodbye_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    reply_keyboard = reply_keyboard_menu_second
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    update.message.reply_text('خوشحالم برگشتی', reply_markup=markup)
    return MENU


def exit(update: Update, context: CallbackContext):
    """ Exit with /exit command after confirmation """
    if 'alert' in context.user_data and context.user_data['alert']:
        reply_keyboard = [['آره'], ['نه']]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        reply_msg = 'اطلاع رسانی فعال است که با خارج شدن شما غیر فعال می شود. آیا می خواهید خارج بشی؟'
        update.message.reply_text(reply_msg, reply_markup=markup)
        return CONFIRM_EXIT
    context.user_data.clear()
    update.message.reply_text(goodbye_msg, reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def error(update: object, context: CallbackContext):
    """ Log errors """
    logger.warning(f'Update {update} caused error {context.error}')


def unknown_handler(update: Update, context: CallbackContext):
    """ Handle unknown messages or commands """
    if session_exists(context) or ('started' in context.user_data and context.user_data['started']):
        reply_msg = 'این دستور وجود ندارد.'
    else:
        reply_msg = restart_msg
    update.message.reply_text(reply_msg)


def keep_awake_heroku(_: CallbackContext):
    """ Keep awake heroku app """
    requests.get(f'https://{HEROKU_APP_NAME}.herokuapp.com/')
    logger.info('Send request to keep awake.')


def admin(update: Update, _: CallbackContext):
    chat_id = update.message.chat_id
    if chat_id == ADMIN_CHAT_ID:
        update.message.reply_text('حالت ادمین فعال شد.\n لطفا پیام خود را برای ارسال به کاربران بفرستید')
        return BROADCAST
    return ConversationHandler.END


def broadcast(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    if chat_id == ADMIN_CHAT_ID:
        for key in db.keys():
            context.bot.sendMessage(db.get(key).decode(), update.message.text)
        update.message.reply_text('پیام به کاربران ارسال شد.')
    return ConversationHandler.END


def main():
    updater = Updater(TOKEN, use_context=True)

    dispatcher = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            USERNAME: [MessageHandler(Filters.regex('^ورود به سامانه$'), username)],
            PASSWORD: [MessageHandler(Filters.text & ~(Filters.command | Filters.regex('^خروج$')), password)],
            LOGIN: [MessageHandler(Filters.text & ~(Filters.command | Filters.regex('^خروج$')), login)],
            MENU: [
                MessageHandler(Filters.regex('^نمایش رویدادهای نزدیک$'), events),
                MessageHandler(Filters.regex('^فعال کردن اطلاع رسانی فعالیت جدید$'), set_alert),
                MessageHandler(Filters.regex('^غیر فعال کردن اطلاع رسانی فعالیت جدید$'), unset_alert),
            ],
            CONFIRM_EXIT: [MessageHandler(Filters.regex('^(آره|نه)$'), confirm_exit)],
        },
        fallbacks=[CommandHandler('exit', exit), MessageHandler(Filters.regex('^خروج$'), exit),
                   CommandHandler('start', start)],
    )
    admin_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin)],
        states={
            BROADCAST: [MessageHandler(Filters.text, broadcast)]
        },
        fallbacks=[]
    )
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(admin_handler)
    dispatcher.add_handler(MessageHandler(Filters.command | Filters.text, unknown_handler))

    job_queue = dispatcher.job_queue
    job_queue.run_repeating(callback=keep_awake_heroku, name='keep_awake', interval=(20 * 60))

    dispatcher.add_error_handler(error)

    updater.start_webhook(listen='0.0.0.0',
                          port=PORT,
                          url_path=TOKEN,
                          webhook_url=f'https://{HEROKU_APP_NAME}.herokuapp.com/' + TOKEN)

    updater.idle()


if __name__ == '__main__':
    main()
