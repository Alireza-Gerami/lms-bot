from bs4 import BeautifulSoup
import requests

BASE_URL = 'https://vlms.ub.ac.ir/'


def sign_in(username, password):
    payload = {
        'logintoken': '',
        'username': username,
        'password': password
    }
    try:
        session = requests.Session()
        response = session.get(url=f'{BASE_URL}login/index.php')
        login_page = BeautifulSoup(response.content, 'html.parser')
        payload['logintoken'] = login_page.find(attrs={"name": "logintoken"})['value']
        response = session.post(url=f'{BASE_URL}login/index.php', data=payload)
        if 'نامعتبر' in response.text:
            return None
        return session
    except Exception:
        return None


def get_events(session):
    events_list = []
    if session:
        try:
            events_page = BeautifulSoup(session.get(f'{BASE_URL}calendar/view.php?view=upcoming').content,
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
            return events_list
        except:
            return None
    else:
        return None
