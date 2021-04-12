from bs4 import BeautifulSoup
import requests

BASE_URL = 'https://vlms.ub.ac.ir/'


def sign_in(username: str, password: str):
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
    try:
        dashboard_page = session.get(f'{BASE_URL}my/', timeout=10).text
        if 'ورود به سامانه' in dashboard_page:
            return False
        return True
    except (requests.exceptions.ReadTimeout, Exception):
        return False


def get_student_courses(session: requests.Session):
    try:
        courses = []
        dashboard_page = BeautifulSoup(session.get(f'{BASE_URL}my/', timeout=10).content, 'html.parser')
        print(dashboard_page)
        for a_tag in dashboard_page.find_all('a', {'class': 'dropdown-item'}):
            if 'https://vlms.ub.ac.ir/course/view.php' in a_tag['href']:
                courses.append({
                    'id': str(a_tag['href']).split('=')[-1],
                    'name': a_tag.text
                })
        return courses, ''
    except (requests.exceptions.ReadTimeout, Exception):
        return None, 'لطفا دوباره تلاش کنید!'


def get_course_activities(session: requests.Session, course_id: str):
    try:
        course_page = BeautifulSoup(session.get(f'{BASE_URL}course/view.php?id={course_id}', timeout=10).content,
                                    'html.parser')
        activities_id = list(course_page.find_all('input', {'name': 'id'}))
        activities_name = course_page.find_all('input', {'name': 'modulename'})
        activities_status = course_page.find_all('input', {'name': 'completionstate'})

        activities = []
        for idx in range(len(activities_id)):
            activities.append(
                {
                    'id': activities_id[idx]['value'],
                    'name': activities_name[idx]['value'],
                    'status': activities_status[idx]['value'],
                }
            )
        return activities, ''
    except (requests.exceptions.ReadTimeout, Exception):
        return None, 'لطفا دوباره تلاش کنید!'


def get_events(session: requests.Session):
    events_list = []
    if session:
        try:
            events_page = BeautifulSoup(session.get(f'{BASE_URL}calendar/view.php?view=upcoming', timeout=10).content,
                                        'html.parser')
            events = events_page.find_all('div', {'class': 'event'})
            for event in events:
                event_name = ' '.join(
                    str(event.find('div', {'class': 'card'}).find('h3', {'class': 'name'}).text).split()).replace(
                    'is due', '')
                event_description = event.find('div', {'class': 'description'})
                event_lesson_name = ' '.join(str(event_description.find_all('div')[-1].text).split())
                event_deadline = ' '.join(str(event_description.find_all('div')[0].text).split())
                event_status = 'تحویل داده شده است. \U00002705' if 'رفتن به فعالیت' in event.find('a', {
                    'class': 'card-link'}).text else 'تحویل داده نشده است. \U0000274C'
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
