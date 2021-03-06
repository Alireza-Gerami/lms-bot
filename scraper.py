from bs4 import BeautifulSoup
import requests

BASE_URL = 'https://vlms.ub.ac.ir/'


def sign_in(username: str, password: str):
    """ Sign in to lms """
    payload = {
        'logintoken': '',
        'username': username,
        'password': password
    }
    try:
        session = requests.Session()
        response = session.get(url=f'{BASE_URL}login/index.php', timeout=10)
        login_page = BeautifulSoup(response.content, 'html.parser')
        payload['logintoken'] = login_page.find(attrs={"name": "logintoken"})['value']
        response = session.post(url=f'{BASE_URL}login/index.php', data=payload, timeout=10)
        if 'نامعتبر' in response.text:
            return None, 'نام کاربری یا رمز ورود نامعتبر است.'
        return session, 'با موفقیت وارد شدید.'
    except (requests.exceptions.ReadTimeout, Exception):
        return None, 'سامانه در دسترس نیست. لطفا بعدا تلاش کنید!'


def session_is_connected(session: requests.Session):
    """ Check user session is connected """
    try:
        dashboard_page = session.get(f'{BASE_URL}my/', timeout=10).text
        if 'ورود به سامانه' in dashboard_page:
            return False
        return True
    except (requests.exceptions.ReadTimeout, Exception):
        return False


def get_student_courses(session: requests.Session):
    """ Find all student courses """
    try:
        courses = []
        dashboard_page = BeautifulSoup(session.get(f'{BASE_URL}my/', timeout=10).content, 'html.parser')
        for a_tag in dashboard_page.find_all('a', {'class': 'dropdown-item'}):
            if 'https://vlms.ub.ac.ir/course/view.php' in a_tag['href']:
                courses.append({
                    'id': str(a_tag['href']).split('=')[-1],
                    'name': clear_text(a_tag.text)
                })
        return courses, ''
    except (requests.exceptions.ReadTimeout, Exception):
        return None, 'لطفا دوباره تلاش کنید!'


def get_course_activities(session: requests.Session, course_id: str):
    """ Find all activities of a course """
    try:
        course_page = BeautifulSoup(session.get(f'{BASE_URL}course/view.php?id={course_id}', timeout=10).content,
                                    'html.parser')
        activities_id = list(course_page.find_all('input', {'name': 'id'}))
        activities_name = course_page.find_all('input', {'name': 'modulename'})
        activities_status = course_page.find_all('input', {'name': 'completionstate'})
        activities = []
        for idx in range(len(activities_id)):
            activity_id = activities_id[idx]['value']
            activity_name = clear_text(activities_name[idx]['value'])
            activity_status = activities_status[idx]['value']
            activity_url = f'{BASE_URL}/mod/resource/view.php?id={activity_id}'
            activities.append(
                {
                    'id': activity_id,
                    'name': activity_name,
                    'status': activity_status,
                    'url': activity_url
                }
            )
        return activities, ''
    except (requests.exceptions.ReadTimeout, Exception):
        return None, 'لطفا دوباره تلاش کنید!'


def get_events(session: requests.Session):
    """ Find upcoming events """
    events_list = []
    if session:
        try:
            events_page = BeautifulSoup(session.get(f'{BASE_URL}calendar/view.php?view=upcoming', timeout=10).content,
                                        'html.parser')
            events = events_page.find_all('div', {'class': 'event'})
            for event in events:
                event_name = clear_text(
                    str(event.find('div', {'class': 'card'}).find('h3', {'class': 'name'}).text))
                event_description = event.find('div', {'class': 'description'})
                event_lesson_name = clear_text(str(event_description.find_all('div')[-1].text))
                event_deadline = clear_text(str(event_description.find_all('div')[0].text))
                if 'closes' in event_name or 'opens' in event_name:
                    event_status = 'انجام نشده است. \U0000274C'
                else:
                    event_status_tag = event.find('a', {'class': 'card-link'})
                    if event_status_tag:
                        event_status = 'تحویل داده شده است. \U00002705' if 'رفتن به فعالیت' in event_status_tag.text else 'تحویل داده نشده است. \U0000274C'
                    else:
                        event_status = 'مشخص نیست'
                events_list.append({
                    'name': event_name,
                    'lesson': event_lesson_name,
                    'deadline': event_deadline,
                    'status': event_status
                })
            return events_list, ''
        except requests.exceptions.ReadTimeout:
            return None, 'لطفا دوباره وارد شوید.'
        except:
            return None, 'لطفا دوباره تلاش کنید!'
    else:
        return None, 'سامانه در دسترس نیست. لطفا بعدا تلاش کنید!'


def clear_text(text: str):
    """ Clear text """
    return ' '.join(text.split())
