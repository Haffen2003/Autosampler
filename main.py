import logging
import json
import os
import requests

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load configuration from config.json
try:
    with open('config.json') as config_file:
        config = json.load(config_file)
        MOONRAKER_URL = config.get('moonraker_url', 'http://default_moonraker_url')
except FileNotFoundError:
    logging.error('Configuration file not found, using default URL.')
    MOONRAKER_URL = 'http://default_moonraker_url'
except json.JSONDecodeError:
    logging.error('Error decoding JSON from configuration file, using default URL.')
    MOONRAKER_URL = 'http://default_moonraker_url'

# Validate icon path with fallback
def validate_icon_path(icon_path):
    if os.path.exists(icon_path):
        return icon_path
    logging.warning('Icon path not found: %s. Using default icon.', icon_path)
    return 'path/to/default/icon.png'

# Improved JSON error handling function
def handle_json_response(response):
    try:
        return response.json()
    except json.JSONDecodeError:
        logging.error('Failed to decode JSON from response: %s', response.text)
        return None

# Moonraker connection function with error handling
def connect_to_moonraker():
    try:
        response = requests.get(MOONRAKER_URL)
        if response.status_code != 200:
            logging.error('Connection failed with status code: %d', response.status_code)
            return None
        return handle_json_response(response)
    except requests.exceptions.RequestException as e:
        logging.error('Error connecting to Moonraker: %s', e)
        return None

# Main preparation function (added race condition fix)
class PreparationScreen:
    def __init__(self):
        # Initialize variables
        self.preparation_in_progress = False

    def start_preparation(self):
        if self.preparation_in_progress:
            logging.warning('Preparation already in progress. Please wait.');
            return
        logging.info('Starting preparation...')
        self.preparation_in_progress = True
        # Do preparation tasks
        # ...
        self.preparation_in_progress = False

class CircleButton:
    def __init__(self, label):
        self.label = label
        # Improved label positioning logic
        self.position_label()

    def position_label(self):
        # Positioning logic for label
        logging.info('Positioning label for button: %s', self.label)
        # ...

# Example usage
if __name__ == '__main__':
    icon_path = validate_icon_path('path/to/icon.png')
    logging.info('Using icon path: %s', icon_path)
    connect_to_moonraker()