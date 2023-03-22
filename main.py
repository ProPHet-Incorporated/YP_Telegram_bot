import logging
import os
import sys
import time
from http import HTTPStatus

import requests
import telegram
from dotenv import load_dotenv

import exceptions

load_dotenv()

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

last_status = False

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] – %(filename)s / %(funcName)s – %(message)s'
)
handler.setFormatter(formatter)
logger.addHandler(handler)


def check_tokens():
    """Check availability of environment variables."""
    tokens = {
        ('PRACTICUM_TOKEN', PRACTICUM_TOKEN),
        ('TELEGRAM_TOKEN', TELEGRAM_TOKEN),
        ('TELEGRAM_CHAT_ID', TELEGRAM_CHAT_ID),
    }
    tokens_missing = [name for name, token in tokens if token is None]
    if tokens_missing:
        msg = f'One or more environment variable not found: {tokens_missing}'
        logger.critical(msg)
        raise exceptions.TokenNotFound(msg)
    logger.debug('Tokens are fine')


def send_message(bot, message):
    """Send message via Telegram."""
    logger.debug('TG message sending initiated')
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
    except telegram.error.TelegramError as error:
        logger.error(f'TG message could not be sent. {error}')
    else:
        logger.debug('TG message sent successfully')


def get_api_answer(timestamp):
    """Get API response from Yandex Practicum."""
    payload = {'from_date': timestamp}
    logger.debug('API request initiated')
    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=payload)
        status_code = response.status_code
    except requests.RequestException as error:
        msg = (
            f"API didn't return correct answer. "
            f'Error {error}. From date: {timestamp}'
        )
        raise exceptions.APIError(msg)
    if status_code != HTTPStatus.OK:
        msg = f'API returned status {status_code}'
        raise exceptions.APIError(msg)
    logger.debug('API responeded properly')
    return response.json()


def check_response(response):
    """Check that API response contains needed data."""
    if not isinstance(response, dict):
        msg = 'Unexpected data structure in API response'
        raise TypeError(msg)
    keys_to_check = ('homeworks', 'current_date')
    for key in keys_to_check:
        if response.get(key) is None:
            msg = f"API response doesn't contain key '{key}'"
            raise exceptions.APIKeyError(msg)
    if not isinstance(response.get('homeworks'), list):
        msg = 'Key `homeworks` in API response is not list type'
        raise TypeError(msg)
    logger.debug('API returned all needed keys properly')


def parse_status(homework):
    """Parse and analize the data structure of a single homework."""
    homework_name = homework.get('homework_name')
    if homework_name is None:
        raise exceptions.HomeworkNameNotFoundError(
            'Key "homework_name" not found in this homework'
        )
    status = homework.get('status')
    if status not in HOMEWORK_VERDICTS:
        msg = f'Unexpected status of homework: "{status}"'
        raise exceptions.HomeworkStatusError(msg)
    verdict = HOMEWORK_VERDICTS[status]
    logger.debug(f'Status parced, verdict is "{verdict}"')
    return (f'Изменился статус проверки работы "{homework_name}". {verdict}')


def main():
    """Engage sequence."""
    check_tokens()

    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    msg = '---Bot engaged'
    logger.debug(msg)
    send_message(bot, msg)
    timestamp = int(time.time())
    current_report = {'homework': None, 'output': None}
    prev_report = current_report.copy()

    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)
            homeworks = response['homeworks']
            if not homeworks:
                logger.debug('No updates in API response')
                continue
            homework = homeworks[0]
            current_report['homework'] = homework['homework_name']
            message = parse_status(homework)
            current_report['output'] = message
            logger.debug(f'---current_report is: {current_report}')
            logger.debug(f'---prev_report is: {prev_report}')

            if current_report != prev_report:
                send_message(bot, message)
                prev_report = current_report.copy()

            timestamp = response['current_date']

        except Exception as error:
            logger.debug('---Exception occured')
            message = f'Something went wrong: {error}'
            logger.error(error)
            current_report['output'] = error
            if current_report != prev_report:
                send_message(bot, f'ERROR – {error}')
                prev_report = current_report.copy()

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()
