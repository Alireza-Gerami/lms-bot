import logging, requests
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext)
from telegram import (ReplyKeyboardMarkup, ReplyKeyboardRemove, ChatAction, Update, ForceReply)
from decouple import config
from scraper import (get_events, sign_in, get_student_courses, get_course_activities, session_is_connected)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)

TOKEN = config('TOKEN')
PORT = int(config('PORT'))
HEROKU_APP_NAME = config('HEROKU_APP_NAME')
logger = logging.getLogger(__name__)

LOGIN, USERNAME, PASSWORD, MENU = range(4)


def start(update: Update, _: CallbackContext):
    reply_keyboard = [['ورود به سامانه']]
    markup = ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    update.message.reply_text(
        f' سلام {update.message.chat.first_name}'
        '\nبه ربات LMS دانشگاه خوش آمدی'
        '\nبرای ادامه کار باید وارد سامانه بشی. (نام کاربری و پسورد هرگز ذخیره نمی شود)'
        '\nاگر منصرف شدی میتونی /cancel رو بفرستی.',
        reply_markup=markup
    )
    return USERNAME


def username(update: Update, _: CallbackContext):
    update.message.reply_text(
        'لطفا نام کاربری را وارد کن', reply_markup=ForceReply())
    return PASSWORD


def password(update: Update, context: CallbackContext):
    context.user_data['username'] = update.message.text
    update.message.reply_text(
        'لطفا رمز ورود را وارد کن', reply_markup=ForceReply())
    return LOGIN


def login(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    context.user_data['password'] = update.message.text
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    session, reply_msg = sign_in(context.user_data['username'], context.user_data["password"])
    if session:
        chat_id = update.message.chat_id
        if job_if_exists(str(chat_id), context):
            reply_keyboard = [['نمایش رویدادها'], ['غیر فعال کردن اطلاع رسانی فعالیت جدید'], ['خروج']]
        else:
            reply_keyboard = [['نمایش رویدادها'], ['فعال کردن اطلاع رسانی فعالیت جدید'], ['خروج']]
        context.user_data['session'] = session
    else:
        reply_keyboard = [['ورود به سامانه']]
    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    update.message.reply_text(
        reply_msg,
        reply_markup=markup,
    )
    return MENU if session else USERNAME


def events(update: Update, context: CallbackContext):
    context.bot.sendChatAction(chat_id=update.message.chat_id, action=ChatAction.TYPING)
    if not session_exists(context):
        reply_msg = 'لطفا دوباره با ارسال /start شروع کنید.'
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
    if 'session' in context.user_data:
        return True
    return False


def job_if_exists(name: str, context: CallbackContext, remove=False):
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    if remove:
        for job in current_jobs:
            job.schedule_removal()
    return True


def alert(context: CallbackContext):
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
    chat_id = update.message.chat_id
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    markup = None
    if not session_exists(context):
        reply_msg = 'لطفا دوباره با ارسال /start شروع کنید.'
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
                reply_keyboard = [['نمایش رویدادها'], ['غیر فعال کردن اطلاع رسانی فعالیت جدید'], ['خروج']]
                markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)

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
    chat_id = update.message.chat_id
    context.bot.sendChatAction(chat_id=chat_id, action=ChatAction.TYPING)
    markup = None
    if not session_exists(context):
        reply_msg = 'لطفا دوباره با ارسال /start شروع کنید.'
        update.message.reply_text(reply_msg, reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if job_if_exists(str(chat_id), context, remove=True):
        reply_keyboard = [['نمایش رویدادها'], ['فعال کردن اطلاع رسانی فعالیت جدید'], ['خروج']]
        markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
        reply_msg = 'اطلاع رسانی فعالیت جدید غیر فعال شد.'
    else:
        reply_msg = 'اطلاع رسانی غیر فعال است.'
    if markup:
        update.message.reply_text(reply_msg, reply_markup=markup)
    else:
        update.message.reply_text(reply_msg)
    return MENU


def cancel(update: Update, _: CallbackContext):
    update.message.reply_text(
        'به امید دیدار'
        '\nبرای شروع دوباره /start رو بفرست.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


def error(update: object, context: CallbackContext):
    logger.warning(f'Update {update} caused error {context.error}')


def unknown_handler(update: Update, context: CallbackContext):
    if session_exists(context):
        reply_msg = 'این دستور وجود ندارد.'
    else:
        reply_msg = 'لطفا دوباره با ارسال /start شروع کنید.'
    update.message.reply_text(reply_msg)


def keep_awake_heroku(_: CallbackContext):
    requests.get(f'https://{HEROKU_APP_NAME}.herokuapp.com/')
    logger.info('Send request to keep awake.')


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
                MessageHandler(Filters.regex('^نمایش رویدادها$'), events),
                MessageHandler(Filters.regex('^فعال کردن اطلاع رسانی فعالیت جدید$'), set_alert),
                MessageHandler(Filters.regex('^غیر فعال کردن اطلاع رسانی فعالیت جدید$'), unset_alert),
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(Filters.regex('^خروج$'), cancel)],
    )
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(MessageHandler(Filters.command | ~Filters.reply, unknown_handler))
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
