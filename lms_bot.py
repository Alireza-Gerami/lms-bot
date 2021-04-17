import logging
import os
import threading
import requests
import redis
import traceback
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext)
from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove, ChatAction, Update, ForceReply)
from decouple import config
from scraper import (get_events, sign_in, get_student_courses, get_course_activities, session_is_connected, BASE_URL)
from bs4 import BeautifulSoup
from gdrive import GDrive

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)

TOKEN = config('TOKEN')
PORT = int(config('PORT'))
HEROKU_APP_NAME = config('HEROKU_APP_NAME')
DB_HOST = config('DB_HOST')
DB_PORT = int(config('DB_PORT'))
DB_PASSWORD = config('DB_PASSWORD')
DB_UPLOAD_HOST = config('DB_UPLOAD_HOST')
DB_UPLOAD_PORT = int(config('DB_UPLOAD_PORT'))
DB_UPLOAD_PASSWORD = config('DB_UPLOAD_PASSWORD')
ADMIN_CHAT_ID = int(config('ADMIN_CHAT_ID'))

# Google drive to upload files
google_drive = GDrive()
google_drive.login()
host_folder = google_drive.get_folder(config('HOST_FOLDER_NAME'))
# Redis db to save chat_id
db = redis.Redis(host=DB_HOST, port=DB_PORT, password=DB_PASSWORD)
# Redis db to save files download link
db_upload = redis.Redis(host=DB_UPLOAD_HOST, port=DB_UPLOAD_PORT, password=DB_UPLOAD_PASSWORD)
logger = logging.getLogger(__name__)

# Conversation handler states
LOGIN, USERNAME, PASSWORD, MENU, CONFIRM_EXIT, BROADCAST, COURSES = range(7)

# Reply keyboards
reply_keyboard_login = [['ورود به سامانه']]
reply_keyboard_menu_first = [['نمایش رویدادهای نزدیک'], ['فعال کردن اطلاع رسانی فعالیت جدید'], ['درس ها'], ['خروج']]
reply_keyboard_menu_second = [['نمایش رویدادهای نزدیک'], ['غیر فعال کردن اطلاع رسانی فعالیت جدید'], ['درس ها'],
                              ['خروج']]

# General messages
welcome_msg = '''**سلام من ربات LMS دانشگاه بجنورد هستم**
من اینجام که بهت کمک کنم تا دیگه** تمرین‌ها** و **امتحان‌ها** رو یادت نره

ویژگی‌های من:

🔹مشاهده رویدادهای نزدیک \(مثل تمرین‌ها و امتحان‌ها\)
🔹اطلاع رسانی فعالیت‌های جدیدی که برای هر درس اضافه میشه

**⚠️برای  شروع باید وارد سامانه LMS بشی اما نگران نباش، نام کاربری و رمز عبور رو به هیچ عنوان ذخیره نمی‌کنم⚠️**

اگر انتقاد یا پیشنهادی داری میتونی به خالق من @IchBin\_Alireza پیام بدی\.
[Github](https://github.com/Alireza-Gerami/lms-bot)
[LMS](https://vlms.ub.ac.ir/)'''
restart_msg = 'لطفا دوباره با ارسال /start شروع کن.'
goodbye_msg = 'به امید دیدار' \
              '\nبرای شروع دوباره /start را بفرست.'
waiting_msg = 'لطفا چند لحظه منتظر بمون...'


def start(update: Update, context: CallbackContext):
    """ Start bot with /start command """
    chat_id = update.message.chat_id
    name = update.message.from_user.username if update.message.from_user.username else update.message.from_user.full_name
    markup = ReplyKeyboardMarkup(reply_keyboard_login, one_time_keyboard=True, resize_keyboard=True)
    if not db.exists(chat_id):
        update.message.reply_text(welcome_msg, reply_markup=markup, parse_mode='MarkdownV2')
        db.set(chat_id, name)
    else:
        update.message.reply_text(
            f' سلام {update.message.chat.first_name}'
            '\nبه ربات LMS دانشگاه خوش آمدی'
            '\nبرای ادامه کار باید وارد سامانه بشی. (نام کاربری و رمز ورود هرگز ذخیره نمی شود)'
            '\nاگر منصرف شدی میتونی /exit رو بفرستی.',
            reply_markup=markup
        )
    context.user_data['started'] = True

    return USERNAME


def username(update: Update, _: CallbackContext):
    """ Getting login information """
    update.message.reply_text(
        'لطفا نام کاربری رو وارد کن', reply_markup=ForceReply())
    return PASSWORD


def password(update: Update, context: CallbackContext):
    """ Getting login information """
    context.user_data['username'] = update.message.text
    update.message.reply_text(
        'لطفا رمز ورود رو وارد کن', reply_markup=ForceReply())
    return LOGIN


def login(update: Update, context: CallbackContext):
    """ Login to lms and set session """
    chat_id = update.message.chat_id
    context.user_data['password'] = update.message.text
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    update.message.reply_text(waiting_msg)
    session, reply_msg = sign_in(context.user_data['username'], context.user_data["password"])
    courses = None
    if session:
        courses, msg = get_student_courses(session)
        if courses:
            chat_id = update.message.chat_id
            if job_if_exists(str(chat_id), context):
                reply_keyboard = reply_keyboard_menu_second
            else:
                reply_keyboard = reply_keyboard_menu_first
            context.user_data['session'] = session
            context.user_data['courses'] = courses
        else:
            reply_msg = msg
            reply_keyboard = reply_keyboard_login
    else:
        reply_keyboard = reply_keyboard_login
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    update.message.reply_text(
        reply_msg,
        reply_markup=markup,
    )
    return MENU if session and courses else USERNAME


def events(update: Update, context: CallbackContext):
    """ Show upcoming events """
    chat_id = update.message.chat_id
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    update.message.reply_text(waiting_msg)
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
    update.message.reply_text(waiting_msg)
    markup = None
    if not session_exists(context):
        reply_msg = restart_msg
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not job_if_exists(str(chat_id), context):
        if not session_is_connected(context.user_data['session']):
            session, msg = sign_in(context.user_data['username'], context.user_data["password"])
            context.user_data['session'] = session
        courses = context.user_data['courses']
        done = True
        for course in courses:
            activities, reply_msg = get_course_activities(context.user_data['session'], course['id'])
            if activities:
                context.user_data[course['id']] = [activity['id'] for activity in activities]
            else:
                done = False
                break
        if done:
            reply_msg = 'اطلاع رسانی فعالیت جدید فعال شد.'
            reply_keyboard = reply_keyboard_menu_second
            markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
            context.user_data['alert'] = True
            context.user_data['chat_id'] = chat_id
            context.job_queue.run_repeating(alert, context=context, name=str(chat_id), interval=1 * 60 * 60)
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


def show_courses(update: Update, context: CallbackContext):
    """ Show student courses """
    if not session_exists(context):
        reply_msg = restart_msg
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not session_is_connected(context.user_data['session']):
        session, msg = sign_in(context.user_data['username'], context.user_data["password"])
        context.user_data['session'] = session
    reply_keyboard_courses = []
    courses = context.user_data['courses']
    for course in courses:
        reply_keyboard_courses.append([f'{course["name"]}'])
    reply_keyboard_courses.append(['برگشت'])
    markup = ReplyKeyboardMarkup(reply_keyboard_courses, resize_keyboard=True)
    update.message.reply_text('لطفا یک درس رو انتخاب کن', reply_markup=markup)
    return COURSES


def show_course_activities(update: Update, context: CallbackContext):
    """ Show activities of selected course """
    if update.message.text == 'برگشت':
        if 'alert' in context.user_data and context.user_data['alert']:
            reply_keyboard = reply_keyboard_menu_second
        else:
            reply_keyboard = reply_keyboard_menu_first
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        update.message.reply_text('انجام شد...', reply_markup=markup)
        return MENU
    courses = context.user_data['courses']
    for course in courses:
        if update.message.text == course['name']:
            activities, msg = get_course_activities(context.user_data['session'], course['id'])
            if activities:
                context.user_data['selected_course'] = {'name': course['name'], 'activities': activities}
                reply_msg = f'فعالیت های درس {course["name"]}\n'
                for activity in activities:
                    status = "مشاهده شده است. \U00002705" if activity[
                                                                 "status"] == "0" else "مشاهده نشده است. \U0000274C"
                    reply_msg += f'\nعنوان فعالیت:   {activity["name"]}\nوضعیت:   {status}\n'
                    reply_msg += f'دانلود:   /download_{activity["id"]}\n'
            else:
                reply_msg = msg
            update.message.reply_text(reply_msg)
            return COURSES
    update.message.reply_text('این درس وجود ندارد!')
    return COURSES


def upload(update: Update, context: CallbackContext):
    """ Upload selected activity """
    chat_id = update.message.chat_id
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    if 'selected_course' not in context.user_data:
        update.message.reply_text('لطفا یک درس رو انتخاب کن')
        return COURSES
    update.message.reply_text(waiting_msg)
    if not session_exists(context):
        reply_msg = restart_msg
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not session_is_connected(context.user_data['session']):
        session, msg = sign_in(context.user_data['username'], context.user_data["password"])
        context.user_data['session'] = session
    session = context.user_data['session']
    threading.Thread(target=generate_download_link, args=(update, context, session)).start()
    return COURSES


def generate_download_link(update: Update, context: CallbackContext, session: requests.Session):
    selected_activity_id = update.message.text.split('_')[-1]
    selected_course = context.user_data['selected_course']
    activities = selected_course['activities']
    for activity in activities:
        if selected_activity_id == activity['id']:
            if db_upload.exists(activity['id']):
                download_link = db_upload.get(activity['id']).decode()
                reply_msg = f'\n<b>نام درس:   {selected_course["name"]}</b>\n\nعنوان فعالیت:   {activity["name"]}\n\n'
                reply_msg += f'<b><a href="{download_link}">📥  دانلود</a></b>\n'
                reply_msg += f'\n\n@ub_lms_bot\n'
                update.message.reply_text(reply_msg, parse_mode='HTML')
                break
            else:
                activity_url = activity['url']
                try:
                    response = session.get(activity_url)
                    if response.status_code == 200:
                        if not response.headers.get(
                                "Content-Disposition"):  # check activity is video or attachment file
                            video_page = BeautifulSoup(response.content, 'html.parser')
                            activity_download_url = video_page.find('source')['src']
                            response = session.get(activity_download_url)
                            filename = get_filename(activity['name'], response.headers.get("Content-Disposition"))
                        else:
                            filename = get_filename(activity['name'], response.headers.get("Content-Disposition"))
                        update.message.reply_text('در حال ایجاد لینک دانلود...')
                        with open(filename, 'wb') as file:
                            file.write(response.content)
                        if google_drive.auth.access_token_expired:
                            google_drive.login()
                        file = google_drive.upload_new_file(filename, host_folder)
                        file.InsertPermission({
                            'type': 'anyone',
                            'value': 'anyone',
                            'role': 'reader'})
                        reply_msg = f'\n<b>نام درس:   {selected_course["name"]}</b>\n\nعنوان فعالیت:   {activity["name"]}\n\n'
                        reply_msg += f'<b><a href="{file["webContentLink"]}">📥  دانلود</a></b>\n'
                        reply_msg += f'\n\n@ub_lms_bot\n'
                        os.remove(filename)
                        db_upload.set(activity['id'], file["webContentLink"], ex=7 * 24 * 60 * 60)
                        update.message.reply_text(reply_msg, parse_mode='HTML')
                    else:
                        update.message.reply_text('این فعالیت فایلی برای دانلود ندارد!')
                    break
                except Exception as e:
                    logging.warning(e)
                    update.message.reply_text('متاسفانه در حال حاظر امکان دانلود وجود ندارد!\n لطفا بعدا تلاش کن...')


def get_filename(activity_name: str, content_description: str):
    extension = content_description.split('.')[-1][:-1]
    return f'{activity_name}.{extension}'


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
    logger.error(f'{traceback.format_exc()} | {update} | {context.error}')


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
    if chat_id == ADMIN_CHAT_ID and update.message.text != 'cancel':
        for key in db.keys():
            context.bot.sendMessage(key.decode(), update.message.text)
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
                MessageHandler(Filters.regex('^درس ها$'), show_courses),
            ],
            COURSES: [MessageHandler(Filters.text & ~Filters.command, show_course_activities),
                      MessageHandler(Filters.command & Filters.regex('^/download_'), upload)],
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
