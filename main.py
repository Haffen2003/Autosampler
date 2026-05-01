import logging
import json
import os
import time
import traceback
from functools import partial

# Windows touchscreens can mis-map coordinates when DPI/touch mouse emulation is active.
os.environ.setdefault('SDL_WINDOWS_DPI_AWARENESS', 'permonitorv2')
os.environ.setdefault('SDL_MOUSE_TOUCH_EVENTS', '0')
os.environ.setdefault('SDL_TOUCH_MOUSE_EVENTS', '0')

# serial communication replaced by Moonraker HTTP API
import requests
from kivy.config import Config
Config.set('graphics', 'fullscreen', 'auto')
# Prevent one physical touch from being processed as additional mouse events.
Config.set('input', 'mouse', 'mouse,disable_on_activity,disable_multitouch')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Console output
        logging.FileHandler('autosampler.log', mode='a', encoding='utf-8')  # File output
    ]
)
logging.info('=== Autosampler Application Starting ===')

# Load configuration
CONFIG_FILE = "config.json"
def load_config():
    """Load configuration from config.json with fallback defaults."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
    except json.JSONDecodeError:
        logging.error(f'Error decoding {CONFIG_FILE}, using defaults')
    except Exception as e:
        logging.error(f'Error loading config: {e}')
    
    return {
        'moonraker_url': 'http://localhost:7125',
        'icon_dir': 'Icons',
        'enable_cocktail_screen': False,
        'z_safety_enabled': True,
        'z_move_speed_mm_min': 1200.0
    }

CONFIG = load_config()
MOONRAKER_URL = CONFIG.get('moonraker_url', 'http://localhost:7125')
TOUCH_ROTATION = int(CONFIG.get('touch_rotation', 180))
ENABLE_COCKTAIL_SCREEN = bool(CONFIG.get('enable_cocktail_screen', False))
CALIBRATION_FILE = "calibration.json"


def default_syringe_calibration_data():
    return {
        'slope_ml_per_mm': None,
        'mm_per_ml': None,
        'points': {}
    }


def load_syringe_calibration_data():
    if not os.path.exists(CALIBRATION_FILE):
        return default_syringe_calibration_data()

    try:
        with open(CALIBRATION_FILE, 'r') as f:
            raw_data = json.load(f)
    except json.JSONDecodeError:
        logging.error(f'Error decoding {CALIBRATION_FILE}, using defaults')
        return default_syringe_calibration_data()
    except Exception as e:
        logging.error(f'Error loading calibration: {e}')
        return default_syringe_calibration_data()

    if not isinstance(raw_data, dict):
        return default_syringe_calibration_data()

    points_raw = raw_data.get('points', {})
    points = points_raw if isinstance(points_raw, dict) else {}

    slope = raw_data.get('slope_ml_per_mm')
    mm_per_ml = raw_data.get('mm_per_ml')
    slope = float(slope) if slope is not None else None
    mm_per_ml = float(mm_per_ml) if mm_per_ml is not None else None

    return {
        'slope_ml_per_mm': slope,
        'mm_per_ml': mm_per_ml,
        'points': {
            '30': points.get('30'),
            '80': points.get('80'),
            '140': points.get('140')
        }
    }


def save_syringe_calibration_data(data):
    try:
        with open(CALIBRATION_FILE, 'w') as f:
            json.dump(data, f, indent=4)
        return True
    except Exception as e:
        logging.error(f'Error saving calibration: {e}')
        return False

# Global syringe calibration data. This is filled from the calibration popup.
SYRINGE_CALIBRATION_DATA = load_syringe_calibration_data()

# base directories for resources
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, CONFIG.get('icon_dir', 'Icons'))
BACKGROUND_DIR = os.path.join(BASE_DIR, 'Background')
COCKTAILS_DIR = os.path.join(BASE_DIR, 'Cocktails')
COCKTAILS_ICON_DIR = os.path.join(COCKTAILS_DIR, '128_192')


def pretty_cocktail_name(filename):
    """Convert icon filename to a readable cocktail label."""
    base_name = os.path.splitext(filename)[0]
    return base_name.replace('_', ' ')


def preferred_ui_font():
    """Pick a bold display font path with cross-platform fallbacks."""
    candidates = [
        os.path.join(BASE_DIR, 'Fonts', 'BebasNeue-Regular.ttf'),
        os.path.join(BASE_DIR, 'Fonts', 'Orbitron-Bold.ttf'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf',
        'C:\\Windows\\Fonts\\bahnschrift.ttf',
        'C:\\Windows\\Fonts\\segoeuib.ttf',
    ]
    for font_path in candidates:
        if os.path.exists(font_path):
            return font_path
    return None

def icon(name):
    """Return full path to an icon file located in the Icons folder with validation."""
    path = os.path.join(ICON_DIR, name)
    if not os.path.exists(path):
        logging.warning(f'Icon not found: {path}')
        return ""
    return path

def background_image(name):
    """Return full path to a background image file with validation."""
    logging.info(f'Looking for background image: {name} in {BACKGROUND_DIR}')
    path = os.path.join(BACKGROUND_DIR, name)
    if not os.path.exists(path):
        fallback_names = ['Schwarz.png', 'Schwarz.jpg', 'schwarz.png', 'schwarz.jpg']
        for fallback in fallback_names:
            fallback_path = os.path.join(BACKGROUND_DIR, fallback)
            if os.path.exists(fallback_path):
                logging.info(f'Background fallback found: {fallback_path}')
                return fallback_path

        logging.error(f'Background image not found: {path}')
        # Try to list what files are actually in the Background directory
        try:
            if os.path.exists(BACKGROUND_DIR):
                files = os.listdir(BACKGROUND_DIR)
                logging.info(f'Files in Background directory: {files}')
            else:
                logging.error(f'Background directory does not exist: {BACKGROUND_DIR}')
        except Exception as e:
            logging.error(f'Error listing Background directory: {e}')
        return ""
    logging.info(f'Background image found: {path}')
    return path

def apply_widget_background(widget, name='Schwarz.png'):
    """Apply a scalable background image to a widget canvas."""
    bg_path = background_image(name)
    if not bg_path:
        return
    from kivy.core.image import Image as CoreImage
    from kivy.graphics.opengl import glGetIntegerv, GL_MAX_TEXTURE_SIZE

    texture_path = bg_path
    try:
        max_texture = int(glGetIntegerv(GL_MAX_TEXTURE_SIZE))
    except Exception:
        max_texture = 4096

    try:
        pil_image_module = __import__('PIL.Image', fromlist=['Image'])
        with pil_image_module.open(bg_path) as img:
            width, height = img.size
            if width > max_texture or height > max_texture:
                scale = min(max_texture / width, max_texture / height)
                new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                resampling = getattr(pil_image_module, 'Resampling', None)
                lanczos = resampling.LANCZOS if resampling else getattr(pil_image_module, 'LANCZOS', 1)
                resized_img = img.resize(new_size, lanczos)
                resized_path = os.path.join(BACKGROUND_DIR, f"_resized_{name.rsplit('.', 1)[0]}_{new_size[0]}x{new_size[1]}.png")
                resized_img.save(resized_path, format='PNG')
                texture_path = resized_path
                logging.info(f'Background resized for GPU limit {max_texture}: {width}x{height} -> {new_size[0]}x{new_size[1]}')
    except ModuleNotFoundError:
        logging.warning('Pillow not installed; cannot resize oversized background image automatically.')
    except Exception as e:
        logging.error(f'Failed to resize background image: {e}')

    try:
        texture = CoreImage(texture_path).texture
        logging.info(f'Background texture loaded: {texture.size} from {texture_path}')
    except Exception as e:
        logging.error(f'Failed to decode background image: {texture_path} ({e})')
        return

    with widget.canvas.before:
        Color(1, 1, 1, 1)
        widget.bg_rect = Rectangle(texture=texture, pos=widget.pos, size=widget.size)

    def _update_bg(instance, _value):
        if hasattr(instance, 'bg_rect'):
            instance.bg_rect.pos = instance.pos
            instance.bg_rect.size = instance.size

    widget.bind(pos=_update_bg, size=_update_bg)

from kivy.core.window import Window
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button as KivyButton
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.slider import Slider
from kivy.uix.spinner import Spinner
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Rectangle, Line
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.uix.switch import Switch
from kivy.uix.popup import Popup
from kivy.properties import NumericProperty
from kivy.clock import Clock
from kivy.metrics import dp


class Button(KivyButton):
    """Custom button with optional touch padding (0 by default to avoid overlap)."""
    touch_padding = NumericProperty(0)

    def collide_point(self, x, y):
        padding = float(self.touch_padding)
        return (
            self.x - padding <= x <= self.right + padding and
            self.y - padding <= y <= self.top + padding
        )

data_file = "cocktails.json"

def save_cocktails(data):
    """Save cocktails to JSON file with error handling."""
    try:
        with open(data_file, "w") as f:
            json.dump(data, f, indent=4)
        logging.info(f'Cocktails saved to {data_file}')
    except IOError as e:
        logging.error(f'Error saving cocktails: {e}')

def load_cocktails():
    """Load cocktails from JSON file with error handling."""
    if os.path.exists(data_file):
        try:
            with open(data_file, "r") as f:
                data = json.load(f)
                logging.info(f'Loaded {len(data)} cocktails')
                return data
        except json.JSONDecodeError:
            logging.error(f'{data_file} is corrupted, returning empty dict')
        except IOError as e:
            logging.error(f'Error reading cocktails: {e}')
    return {}

class CocktailInputScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cocktail_data = load_cocktails()
        self.ingredients = []

        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)

        self.name_input = TextInput(hint_text="Cocktail Name", size_hint_y=None, height=40)
        self.ingredient_input = TextInput(hint_text="Zutat (z.B. Rum)", size_hint_y=None, height=40)
        self.amount_input = TextInput(hint_text="Menge in ml", size_hint_y=None, height=40)

        self.add_button = Button(text="Zutat hinzufügen", size_hint_y=None, height=40)
        self.save_button = Button(text="Cocktail speichern", size_hint_y=None, height=40)
        self.refresh_button = Button(text="Aktualisieren", size_hint_y=None, height=40)

        self.status_label = Label(text="", size_hint_y=None, height=40)

        # Zutatenliste anzeigen
        self.ingredients_area = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5)
        self.ingredients_area.bind(minimum_height=self.ingredients_area.setter('height'))

        self.scroll = ScrollView(size_hint=(1, 1))
        self.scroll.add_widget(self.ingredients_area)

        # Button-Verknüpfung
        self.add_button.bind(on_press=self.add_ingredient)
        self.save_button.bind(on_press=self.save_cocktail)
        self.refresh_button.bind(on_press=self.refresh_cocktails)

        # Aufbau
        layout.add_widget(self.name_input)
        layout.add_widget(self.ingredient_input)
        layout.add_widget(self.amount_input)
        layout.add_widget(self.add_button)
        layout.add_widget(self.scroll)
        layout.add_widget(self.save_button)
        layout.add_widget(self.refresh_button)
        layout.add_widget(self.status_label)

        self.add_widget(layout)

    def add_ingredient(self, instance):
        name = self.ingredient_input.text.strip()
        amount = self.amount_input.text.strip()
        if name and amount.isdigit():
            self.ingredients.append({"name": name, "amount": int(amount)})
            label = Label(text=f"{name}: {amount} ml", size_hint_y=None, height=30)
            self.ingredients_area.add_widget(label)
            self.status_label.text = f"Zutat hinzugefügt: {name} ({amount} ml)"
            self.ingredient_input.text = ""
            self.amount_input.text = ""
        else:
            self.status_label.text = "[WARN] Bitte gültige Zutat und Menge eingeben."

    def save_cocktail(self, instance):
        name = self.name_input.text.strip()
        if name and self.ingredients:
            self.cocktail_data[name] = self.ingredients
            save_cocktails(self.cocktail_data)
            self.status_label.text = f"Cocktail '{name}' gespeichert!"
            self.name_input.text = ""
            self.ingredients = []
            self.ingredients_area.clear_widgets()
        else:
            self.status_label.text = "[WARN] Bitte Namen und mindestens eine Zutat eingeben."

    def refresh_cocktails(self, instance):
        self.cocktail_data = load_cocktails()
        self.status_label.text = "[INFO] Cocktaildaten aktualisiert."

        # Zugriff auf PreparationScreen
        try:
            prep_screen = self.manager.get_screen("prep")
            prep_screen.cocktail_data = self.cocktail_data
            prep_screen.spinner.values = list(self.cocktail_data.keys())
            self.status_label.text += " → Zubereitung aktualisiert."
        except Exception as e:
            logging.error(f'Error updating prep screen: {e}')

class MoonrakerClient:
    """Moonraker client with robust error handling and retry logic."""
    def __init__(self, base_url=None):
        self.base_url = (base_url or MOONRAKER_URL).rstrip('/')
        self.timeout = 5

    def send_gcode(self, gcode: str, timeout_s=None):
        """Send G-code to printer via Moonraker API with error handling."""
        url = f"{self.base_url}/printer/gcode/script"
        request_timeout = self.timeout if timeout_s is None else max(0.1, float(timeout_s))
        try:
            resp = requests.post(
                url,
                json={"script": gcode},
                timeout=request_timeout
            )
            if resp.status_code not in [200, 204]:
                logging.error(f'Moonraker error {resp.status_code}: {resp.text}')
                return False
            logging.info(f'G-code sent: {gcode}')
            return True
        except requests.exceptions.Timeout:
            logging.error(f'Timeout sending G-code to {url} (timeout={request_timeout}s)')
            return False
        except requests.exceptions.ConnectionError:
            logging.error(f'Cannot connect to Moonraker at {self.base_url}')
            return False
        except Exception as e:
            logging.error(f'Error sending G-code: {e}')
            return False

    def get_console_lines(self, count: int = 50):
        """Fetch recent console lines from Moonraker gcode store."""
        url = f"{self.base_url}/server/gcode_store"
        try:
            resp = requests.get(url, params={"count": max(1, int(count))}, timeout=self.timeout)
            if resp.status_code != 200:
                logging.error(f'G-code store error {resp.status_code}: {resp.text}')
                return []

            payload = resp.json() if resp.content else {}
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            gcode_store = result.get("gcode_store", []) if isinstance(result, dict) else []
            if not isinstance(gcode_store, list):
                return []

            parsed_lines = []
            for item in gcode_store:
                if not isinstance(item, dict):
                    continue
                msg_type = str(item.get("type", "info")).upper()
                message = str(item.get("message", "")).strip()
                if not message:
                    continue
                parsed_lines.append(f"[{msg_type}] {message}")

            return parsed_lines
        except requests.exceptions.Timeout:
            logging.error(f'Timeout fetching gcode store from {url}')
            return []
        except requests.exceptions.ConnectionError:
            logging.error(f'Cannot connect to Moonraker at {self.base_url}')
            return []
        except Exception as e:
            logging.error(f'Error fetching gcode store: {e}')
            return []

    def get_printer_temperatures(self):
        """Fetch printer temperatures from Moonraker objects query."""
        url = f"{self.base_url}/printer/objects/query"
        params = {
            "extruder": "temperature,target",
            "heater_bed": "temperature,target"
        }

        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logging.error(f'Temperature query error {resp.status_code}: {resp.text}')
                return {}

            payload = resp.json() if resp.content else {}
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            status = result.get("status", {}) if isinstance(result, dict) else {}

            temperatures = {}
            extruder_data = status.get("extruder", {}) if isinstance(status, dict) else {}
            if isinstance(extruder_data, dict):
                if "temperature" in extruder_data:
                    temperatures["extruder"] = float(extruder_data.get("temperature", 0.0))
                if "target" in extruder_data:
                    temperatures["extruder_target"] = float(extruder_data.get("target", 0.0))

            bed_data = status.get("heater_bed", {}) if isinstance(status, dict) else {}
            if isinstance(bed_data, dict):
                if "temperature" in bed_data:
                    temperatures["bed"] = float(bed_data.get("temperature", 0.0))
                if "target" in bed_data:
                    temperatures["bed_target"] = float(bed_data.get("target", 0.0))

            return temperatures
        except requests.exceptions.Timeout:
            logging.error(f'Timeout fetching temperatures from {url}')
            return {}
        except requests.exceptions.ConnectionError:
            logging.error(f'Cannot connect to Moonraker at {self.base_url}')
            return {}
        except Exception as e:
            logging.error(f'Error fetching temperatures: {e}')
            return {}

    def get_current_z_position(self):
        """Fetch current toolhead Z position from Moonraker."""
        url = f"{self.base_url}/printer/objects/query"
        params = {"toolhead": "position"}
        try:
            resp = requests.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logging.error(f'Toolhead query error {resp.status_code}: {resp.text}')
                return None

            payload = resp.json() if resp.content else {}
            result = payload.get("result", {}) if isinstance(payload, dict) else {}
            status = result.get("status", {}) if isinstance(result, dict) else {}
            toolhead = status.get("toolhead", {}) if isinstance(status, dict) else {}
            position = toolhead.get("position") if isinstance(toolhead, dict) else None

            if isinstance(position, (list, tuple)) and len(position) >= 3:
                return float(position[2])
            return None
        except requests.exceptions.Timeout:
            logging.error(f'Timeout fetching toolhead position from {url}')
            return None
        except requests.exceptions.ConnectionError:
            logging.error(f'Cannot connect to Moonraker at {self.base_url}')
            return None
        except Exception as e:
            logging.error(f'Error fetching toolhead position: {e}')
            return None

# singleton instance
moonraker = MoonrakerClient()

class CircleButton(Widget):
    def __init__(self, index, callback, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (100, 100)
        self.index = index
        self.callback = callback
        self.assigned_ingredient = None
        self.is_selected = False

        self.default_color = (0.36, 0.68, 0.89, 1)
        self.selected_color = (1, 0, 0, 1)

        with self.canvas:
            self.color_instruction = Color(*self.default_color)
            self.circle = Ellipse(pos=self.pos, size=self.size)

        self.label = Label(
            text="",
            size=self.size,
            pos=self.pos,
            font_size=18,
            halign='center',
            valign='middle',
            color=[1, 1, 1, 1]
        )
        self.label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
        self.add_widget(self.label)

        self.bind(pos=self.update_circle, size=self.update_circle)

    def update_circle(self, *args):
        self.circle.pos = self.pos
        self.circle.size = self.size
        self.label.pos = self.pos
        self.label.size = self.size

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if callable(self.callback):
                self.callback(self)
            return True
        return super().on_touch_down(touch)

    def assign_ingredient(self, name, color):
        self.assigned_ingredient = name
        self.color_instruction.rgb = color[:3]
        self.label.text = name

    def set_selected(self, selected):
        self.is_selected = selected
        self.color_instruction.rgb = self.selected_color[:3] if selected else self.default_color[:3]

class PreparationScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cocktail_data = load_cocktails()
        self.active_color = None
        self.active_ingredient_name = None
        self.assigned_ingredients = set()
        self._loading_ingredients = False  # Race condition fix

        self.layout = FloatLayout()

        # Inhaltsbereich oben
        content_height = Window.height * 0.6
        scroll_height = content_height - 50

        self.content_area = BoxLayout(orientation='vertical', size_hint=(1, None), height=content_height, pos_hint={'top': 1})
        
        # Ensure spinner always has values and a valid initial selection
        cocktail_names = list(self.cocktail_data.keys())
        if not cocktail_names:
            cocktail_names = ["Keine Cocktails verfügbar"]
        
        self.spinner = Spinner(
            text="Cocktail auswählen",
            values=cocktail_names,
            size_hint_y=None,
            height=50,
            font_size=18
        )
        self.spinner.bind(text=self.show_ingredients)

        self.ingredients_area = BoxLayout(orientation='vertical', size_hint_y=None, spacing=10)
        self.ingredients_area.bind(minimum_height=self.ingredients_area.setter('height'))

        self.scroll = ScrollView(size_hint=(1, None), height=scroll_height)
        self.scroll.add_widget(self.ingredients_area)

        self.content_area.add_widget(self.spinner)
        self.content_area.add_widget(self.scroll)
        self.layout.add_widget(self.content_area)

        # Kreise unten mittig
        circle_width = min(Window.width * 0.9, 600)
        self.slot_area = GridLayout(cols=5, spacing=[8, 8], size_hint=(None, None), size=(circle_width, circle_width * 0.5))
        self.slot_area.pos_hint = {'center_x': 0.5, 'y': 0.05}
        self.draw_circles()
        self.layout.add_widget(self.slot_area)

        self.add_widget(self.layout)

    def show_ingredients(self, spinner, text):
        """Load ingredients with race condition protection."""
        if self._loading_ingredients:
            logging.warning('Already loading ingredients, skipping')
            return
        
        # Skip if no cocktails available or initial text
        if text == "Cocktail auswählen" or text == "Keine Cocktails verfügbar":
            return
        
        self._loading_ingredients = True
        try:
            self.active_color = None
            self.active_ingredient_name = None
            self.cocktail_data = load_cocktails()

            # Clear existing widgets to prevent duplicates
            self.ingredients_area.clear_widgets()

            # Neue Zutaten hinzufügen
            ingredients = self.cocktail_data.get(text, [])
            if not ingredients:
                logging.warning(f'No ingredients found for cocktail: {text}')
                self.ingredients_area.add_widget(Label(text="Keine Zutaten verfügbar", size_hint_y=None, height=50, color=[1, 1, 1, 1]))
                self._loading_ingredients = False
                return
            
            for i in ingredients:
                try:
                    # Validate ingredient structure
                    if not isinstance(i, dict) or 'name' not in i or 'amount' not in i:
                        logging.warning(f'Invalid ingredient structure: {i}')
                        continue
                    
                    row = BoxLayout(size_hint_y=None, height=50, spacing=10, padding=[5, 5, 5, 5])
                    row.ingredient_name = i['name']

                    bg_box = FloatLayout(size_hint=(None, None), size=(40, 40))
                    with bg_box.canvas.before:
                        Color(0.2, 0.2, 0.2, 1)
                        rect = Rectangle(pos=bg_box.pos, size=bg_box.size)
                        bg_box.rect = rect

                    bg_box.bind(pos=lambda inst, val: setattr(inst.rect, 'pos', inst.pos))
                    bg_box.bind(size=lambda inst, val: setattr(inst.rect, 'size', inst.size))

                    stift_icon = icon('stift.40.png')
                    activate_btn = Button(
                        size_hint=(None, None),
                        size=(40, 40),
                        pos_hint={'center_x': 0.5, 'center_y': 0.5},
                        background_normal=stift_icon if stift_icon else '',
                        background_down=stift_icon if stift_icon else '',
                        background_color=(1, 1, 1, 1)
                    )
                    activate_btn.bind(on_press=partial(self.set_active_color, name=i['name'], color=i.get('color', [1, 0, 0, 1])))
                    row.activate_btn = activate_btn
                    bg_box.add_widget(activate_btn)

                    label = Label(
                        text=f"{i['name']}: {i['amount']} ml",
                        size_hint_x=1,
                        halign='left',
                        valign='middle',
                        color=[1, 1, 1, 1],
                        font_size=16
                    )
                    label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))

                    muell_icon = icon('müll.40.png')
                    delete_btn = Button(
                        size_hint=(None, None),
                        size=(40, 40),
                        background_normal=muell_icon if muell_icon else '',
                        background_down=muell_icon if muell_icon else ''
                    )
                    delete_btn.row = row
                    delete_btn.bind(on_press=self.remove_row)

                    row.add_widget(bg_box)
                    row.add_widget(label)
                    row.add_widget(delete_btn)
                    self.ingredients_area.add_widget(row)
                except KeyError as e:
                    logging.error(f'KeyError processing ingredient: {e}, ingredient: {i}')
                except Exception as e:
                    logging.error(f'Error processing ingredient {i}: {e}')
        finally:
            self._loading_ingredients = False

    def remove_row(self, button):
        row = getattr(button, 'row', None)
        if not row:
            return

        ingredient_name = getattr(row, 'ingredient_name', None)
        if ingredient_name:
            for btn in self.slot_area.children:
                if isinstance(btn, CircleButton) and btn.assigned_ingredient == ingredient_name:
                    btn.assigned_ingredient = None
                    btn.label.text = ""
                    btn.color_instruction.rgb = btn.default_color[:3]

        self.ingredients_area.remove_widget(row)

    def set_active_color(self, button, name, color):
        self.active_color = color
        self.active_ingredient_name = name

        # Alle Stifte zurücksetzen
        for row in self.ingredients_area.children:
            if hasattr(row, 'activate_btn'):
                row.activate_btn.background_color = (1, 1, 1, 1)

        # Geklickten Stift rot färben
        button.background_color = (1, 0, 0, 1)

    def draw_circles(self):
        self.slot_area.clear_widgets()
        for i in range(15):
            circle = CircleButton(index=i + 1, callback=self.select_circle)
            self.slot_area.add_widget(circle)

    def select_circle(self, instance):
        if not self.active_color or not self.active_ingredient_name:
            return

        for btn in self.slot_area.children:
            if isinstance(btn, CircleButton) and btn.assigned_ingredient == self.active_ingredient_name:
                logging.warning('Diese Zutat wurde bereits zugewiesen.')
                return

        instance.assign_ingredient(self.active_ingredient_name, self.active_color)
        logging.info(f"Zutat '{self.active_ingredient_name}' zu Slot {instance.index} zugewiesen.")
        self.active_color = None
        self.active_ingredient_name = None
        self.reset_stift_buttons()

    def reset_stift_buttons(self):
        for row in self.ingredients_area.children:
            if hasattr(row, 'activate_btn'):
                row.activate_btn.background_color = (1, 1, 1, 1)

class MotorPositionScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.default_slot_speed = 8000.0
        self.max_slot_speed = 8000.0
        self._speed_editing = False
        self.positions = self.load_positions()
        self.selected_circle = None
        self.z_reference_known = False
        self.z_is_zero = False
        self.z_zero_tolerance = 0.05
        self.z_safety_enabled = bool(CONFIG.get('z_safety_enabled', True))
        self.z_move_speed = float(CONFIG.get('z_move_speed_mm_min', 1200.0))

        self.layout = BoxLayout(orientation='vertical', padding=5, spacing=5)

        # Oberer Bereich: Kreise links, Home-Buttons oben rechts
        top_area = BoxLayout(orientation='horizontal', size_hint=(1, 0.6), spacing=6, padding=[5, 5, 5, 5])

        self.slot_area = GridLayout(cols=5, spacing=[10, 10], size_hint=(1, 1), padding=5)
        self.draw_circles()
        top_area.add_widget(self.slot_area)

        home_column = BoxLayout(orientation='vertical', size_hint=(None, 1), width=142, spacing=6)

        self.home_x_btn = Button(text="X", size_hint=(None, None), size=(64, 64), font_size=18)
        self.home_y_btn = Button(text="Y", size_hint=(None, None), size=(64, 64), font_size=18)
        self.home_z_btn = Button(text="Z", size_hint=(None, None), size=(64, 64), font_size=18)
        self.home_all_btn = Button(text="", size_hint=(None, None), size=(64, 64))
        self.z_up_btn = Button(text="Z Up", size_hint=(None, None), size=(64, 64), font_size=14)
        self.z_down_btn = Button(text="Z Down", size_hint=(None, None), size=(64, 64), font_size=13)

        home_all_icon = Image(source=icon('haus.40.png'), size_hint=(None, None), size=(40, 40))

        def update_home_icon(*_args):
            home_all_icon.center = self.home_all_btn.center

        self.home_all_btn.bind(pos=update_home_icon, size=update_home_icon)
        self.home_all_btn.add_widget(home_all_icon)
        update_home_icon()

        self.home_x_btn.bind(on_press=partial(self.home_axis, axis='X'))
        self.home_y_btn.bind(on_press=partial(self.home_axis, axis='Y'))
        self.home_z_btn.bind(on_press=partial(self.home_axis, axis='Z'))
        self.home_all_btn.bind(on_press=self.home_all_axes)
        self.z_up_btn.bind(on_press=self.move_z_up_to_zero)
        self.z_down_btn.bind(on_press=self.move_z_down_to_endstop)

        motor_off_btn = Button(text="", size_hint=(None, None), size=(64, 64))
        motor_off_icon = Image(source=icon('aus.40.png'), size_hint=(None, None), size=(40, 40))

        def update_motor_off_icon(*_args):
            motor_off_icon.center = motor_off_btn.center

        motor_off_btn.bind(pos=update_motor_off_icon, size=update_motor_off_icon)
        motor_off_btn.add_widget(motor_off_icon)
        update_motor_off_icon()
        motor_off_btn.bind(on_press=self.disable_motors)

        top_row = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(134, 64), spacing=6)
        top_row.add_widget(self.home_x_btn)
        top_row.add_widget(Widget(size_hint=(None, None), size=(64, 64)))

        mid_row = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(134, 64), spacing=6)
        mid_row.add_widget(self.home_y_btn)
        mid_row.add_widget(self.z_up_btn)

        low_row = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(134, 64), spacing=6)
        low_row.add_widget(self.home_z_btn)
        low_row.add_widget(self.z_down_btn)

        bottom_home_row = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(134, 64), spacing=6)
        bottom_home_row.add_widget(self.home_all_btn)
        bottom_home_row.add_widget(motor_off_btn)

        home_column.add_widget(top_row)
        home_column.add_widget(mid_row)
        home_column.add_widget(low_row)
        home_column.add_widget(bottom_home_row)

        top_area.add_widget(home_column)
        self.layout.add_widget(top_area)

        # Eingabefelder und Buttons unten
        input_area = BoxLayout(orientation='horizontal', size_hint=(1, 0.4), spacing=5, padding=5)

        # Linke Seite: Eingabefelder
        input_box = BoxLayout(orientation='vertical', size_hint=(0.6, 1), spacing=3)
        
        x_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=35, spacing=3)
        x_row.add_widget(Label(text="X:", size_hint=(None, 1), width=30, font_size=14))
        self.x_input = TextInput(hint_text="X", multiline=False, size_hint=(1, 1), font_size=12)
        x_row.add_widget(self.x_input)
        input_box.add_widget(x_row)
        
        y_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=35, spacing=3)
        y_row.add_widget(Label(text="Y:", size_hint=(None, 1), width=30, font_size=14))
        self.y_input = TextInput(hint_text="Y", multiline=False, size_hint=(1, 1), font_size=12)
        y_row.add_widget(self.y_input)
        input_box.add_widget(y_row)

        speed_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=35, spacing=3)
        speed_row.add_widget(Label(text="V:", size_hint=(None, 1), width=30, font_size=14))
        self.speed_input = TextInput(hint_text="Geschwindigkeit (mm/min)", multiline=False, size_hint=(1, 1), font_size=12)
        self.speed_input.bind(text=self.on_speed_input_text)
        speed_row.add_widget(self.speed_input)
        input_box.add_widget(speed_row)

        safety_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=35, spacing=3)
        safety_row.add_widget(Label(text="Z-Safe:", size_hint=(None, 1), width=60, font_size=14))
        self.z_safety_switch = Switch(active=self.z_safety_enabled, size_hint=(None, None), size=(56, 34))
        self.z_safety_switch.bind(active=self.on_z_safety_toggle)
        safety_row.add_widget(self.z_safety_switch)
        self.z_safety_value_label = Label(
            text="AN" if self.z_safety_enabled else "AUS",
            size_hint=(None, 1),
            width=40,
            font_size=12
        )
        safety_row.add_widget(self.z_safety_value_label)
        input_box.add_widget(safety_row)
        
        input_area.add_widget(input_box)

        # Rechte Seite: Buttons
        button_box = BoxLayout(orientation='vertical', size_hint=(0.4, 1), spacing=3)
        
        save_btn = Button(text="Speichern", size_hint=(1, 0.5), font_size=12)
        save_btn.bind(on_press=self.save_position)
        button_box.add_widget(save_btn)
        
        send_btn = Button(text="Senden", size_hint=(1, 0.5), font_size=12)
        send_btn.bind(on_press=self.send_position)
        button_box.add_widget(send_btn)
        
        input_area.add_widget(button_box)
        self.layout.add_widget(input_area)

        self.status_label = Label(
            text="Bereit",
            size_hint=(1, None),
            height=34,
            color=[1, 1, 1, 1],
            halign='left',
            valign='middle',
            font_size=13,
            padding=(8, 0)
        )
        self.status_label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
        self.layout.add_widget(self.status_label)

        self.add_widget(self.layout)
        self.update_xy_home_lock_state(refresh_z_position=False)

    def set_status(self, message, level='info'):
        """Update status text in the motor UI."""
        colors = {
            'info': [1, 1, 1, 1],
            'success': [0.4, 1, 0.4, 1],
            'warn': [1, 0.85, 0.3, 1],
            'error': [1, 0.4, 0.4, 1]
        }
        self.status_label.text = message
        self.status_label.color = colors.get(level, colors['info'])

    def _parse_float(self, text):
        return float(str(text).strip().replace(',', '.'))

    def _fmt_number(self, value):
        as_float = float(value)
        if as_float.is_integer():
            return str(int(as_float))
        return f"{as_float:.3f}".rstrip('0').rstrip('.')

    def _set_button_enabled(self, button, enabled):
        button.disabled = not enabled
        button.opacity = 1.0 if enabled else 0.4

    def _clamp_speed(self, speed_value):
        speed = float(speed_value)
        if speed <= 0:
            raise ValueError
        return min(speed, self.max_slot_speed)

    def on_speed_input_text(self, instance, value):
        if self._speed_editing:
            return

        raw = str(value).strip()
        if raw == "":
            return

        normalized = raw.replace(',', '.')
        try:
            capped = self._clamp_speed(normalized)
        except ValueError:
            return

        formatted = self._fmt_number(capped)
        if instance.text != formatted:
            self._speed_editing = True
            instance.text = formatted
            self._speed_editing = False

    def default_slot_positions(self):
        defaults = {}
        x_values = [400.0, 300.0, 200.0, 100.0, 0.0]
        y_values = [0.0, 80.0, 160.0]
        index = 1
        for y in y_values:
            for x in x_values:
                defaults[str(index)] = {
                    "x": x,
                    "y": y,
                    "speed": self.default_slot_speed
                }
                index += 1
        return defaults

    def wait_for_z_feedback(self, timeout_s=8.0, poll_interval_s=0.2):
        """Wait until a valid Z position can be read from Moonraker."""
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        while time.monotonic() < deadline:
            z_value = moonraker.get_current_z_position()
            if z_value is not None:
                return True, float(z_value)
            time.sleep(max(0.05, float(poll_interval_s)))
        return False, None

    def wait_for_z_target(self, target=0.0, timeout_s=12.0, poll_interval_s=0.2, settle_time_s=0.3):
        """Wait until Z reaches target and stays there briefly to avoid stale/early reads."""
        target_value = float(target)
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        reached_since = None
        last_z = None

        while time.monotonic() < deadline:
            z_value = moonraker.get_current_z_position()
            if z_value is None:
                reached_since = None
                time.sleep(max(0.05, float(poll_interval_s)))
                continue

            last_z = float(z_value)
            if abs(last_z - target_value) <= self.z_zero_tolerance:
                now = time.monotonic()
                if reached_since is None:
                    reached_since = now
                elif (now - reached_since) >= max(0.0, float(settle_time_s)):
                    return True, last_z
            else:
                reached_since = None

            time.sleep(max(0.05, float(poll_interval_s)))

        return False, last_z

    def update_xy_home_lock_state(self, refresh_z_position=True):
        if refresh_z_position:
            current_z = moonraker.get_current_z_position()
            self.z_is_zero = current_z is not None and abs(current_z) <= self.z_zero_tolerance

        if self.z_safety_enabled:
            xy_allowed = self.z_reference_known and self.z_is_zero
        else:
            xy_allowed = True

        self._set_button_enabled(self.home_x_btn, xy_allowed)
        self._set_button_enabled(self.home_y_btn, xy_allowed)

        z_manual_allowed = self.z_reference_known
        self._set_button_enabled(self.z_up_btn, z_manual_allowed)
        self._set_button_enabled(self.z_down_btn, z_manual_allowed)

    def draw_circles(self):
        self.slot_area.clear_widgets()
        for i in range(15):
            circle = CircleButton(index=i + 1, callback=self.select_circle)
            self.slot_area.add_widget(circle)

    def select_circle(self, instance):
        for btn in self.slot_area.children:
            if isinstance(btn, CircleButton):
                btn.set_selected(False)
        instance.set_selected(True)
        self.selected_circle = instance

        pos = self.positions.get(str(instance.index), {"x": "", "y": "", "speed": self.default_slot_speed})
        self.x_input.text = str(pos.get("x", ""))
        self.y_input.text = str(pos.get("y", ""))
        self.speed_input.text = str(pos.get("speed", self.default_slot_speed))
        logging.info(f"Slot {instance.index} ausgewählt")

    def save_position(self, instance):
        if not self.selected_circle:
            logging.warning("Kein Slot ausgewählt.")
            self.set_status("Kein Slot ausgewählt.", "warn")
            return

        x_text = self.x_input.text.strip()
        y_text = self.y_input.text.strip()
        speed_text = self.speed_input.text.strip()
        if not x_text or not y_text or not speed_text:
            logging.warning("Ungültige Koordinaten.")
            self.set_status("Bitte X, Y und Geschwindigkeit eingeben.", "warn")
            return

        try:
            x = self._parse_float(x_text)
            y = self._parse_float(y_text)
            speed = self._clamp_speed(self._parse_float(speed_text))
        except ValueError:
            logging.warning("Ungültige Koordinaten oder Geschwindigkeit.")
            self.set_status("Ungültige Werte: X/Y oder Geschwindigkeit.", "warn")
            return

        self.speed_input.text = self._fmt_number(speed)

        self.positions[str(self.selected_circle.index)] = {
            "x": x,
            "y": y,
            "speed": speed
        }
        self.store_positions()
        logging.info(f"Slot {self.selected_circle.index} → X={x}, Y={y}, V={speed}")
        self.set_status(f"Slot {self.selected_circle.index}: Position + V gespeichert", "success")

    def send_position(self, instance):
        """Send G-code move command to stored coordinates."""
        if self.selected_circle:
            pos = self.positions.get(str(self.selected_circle.index))
            if pos:
                target_x = pos['x']
                target_y = pos['y']
                target_speed = pos.get('speed')

                if target_speed is None:
                    logging.warning(f"No speed saved for slot {self.selected_circle.index}")
                    self.set_status("Keine Geschwindigkeit gespeichert", "warn")
                    return

                try:
                    target_speed = self._clamp_speed(self._parse_float(target_speed))
                except (TypeError, ValueError):
                    logging.warning(f"Invalid speed for slot {self.selected_circle.index}: {target_speed}")
                    self.set_status("Ungültige Geschwindigkeit im Slot", "warn")
                    return

                if self.z_safety_enabled:
                    if not self.ensure_z_homed_and_zero():
                        logging.error("Blocked XY move because Z safety sequence failed")
                        self.set_status("XY gesperrt: zuerst Z homing + Z0 erforderlich", "error")
                        return

                if not moonraker.send_gcode("G90"):
                    self.set_status("Fehler: G90 konnte nicht gesetzt werden", "error")
                    return

                speed_value = self._fmt_number(target_speed)
                if not moonraker.send_gcode(f"G1 F{speed_value}"):
                    self.set_status("Fehler: Geschwindigkeit konnte nicht gesetzt werden", "error")
                    return

                command = f"G1 X{self._fmt_number(target_x)} Y{self._fmt_number(target_y)}"
                if moonraker.send_gcode(command):
                    if self.z_safety_enabled:
                        logging.info(f"Moved to X={target_x}, Y={target_y} with F={speed_value} after Z home + Z0 safety sequence")
                    else:
                        logging.info(f"Moved to X={target_x}, Y={target_y} with F={speed_value} while Z safety disabled")
                    self.set_status(f"Bewegt auf X={target_x}, Y={target_y} mit F={speed_value}", "success")
                else:
                    self.set_status("XY-Fahrt fehlgeschlagen", "error")
            else:
                logging.warning(f"No position saved for slot {self.selected_circle.index}")
                self.set_status("Kein Wert für gewählten Slot gespeichert", "warn")

    def on_z_safety_toggle(self, _instance, active):
        self.z_safety_enabled = bool(active)
        self.z_safety_value_label.text = "AN" if self.z_safety_enabled else "AUS"
        self.update_xy_home_lock_state(refresh_z_position=True)
        if self.z_safety_enabled:
            logging.info("Z safety sequence enabled")
            self.set_status("Z-Sicherheitssequenz aktiviert", "info")
        else:
            logging.warning("Z safety sequence disabled via debug switch")
            self.set_status("Debug: Z-Sicherheitssequenz deaktiviert", "warn")

    def ensure_z_homed_and_zero(self, force_rehome=False):
        """Ensure Z is safe before XY: re-home only when required, otherwise keep Z at 0."""
        if not self.z_safety_enabled:
            logging.warning("Skipped Z safety sequence because debug switch is off")
            self.update_xy_home_lock_state(refresh_z_position=True)
            return True

        if not moonraker.send_gcode("G90"):
            logging.error("Failed to set absolute positioning (G90)")
            self.set_status("Fehler: G90 konnte nicht gesetzt werden", "error")
            return False

        requires_reference = force_rehome or not self.z_reference_known
        if requires_reference:
            self.set_status("Sicherheitssequenz: Z wird gehomed...", "warn")
            if not moonraker.send_gcode("G28 Z", timeout_s=45.0):
                logging.error("Failed to home Z axis")
                self.set_status("Fehler: Z konnte nicht gehomed werden", "error")
                self.z_reference_known = False
                self.z_is_zero = False
                self.update_xy_home_lock_state(refresh_z_position=False)
                return False

            self.z_reference_known = True
            self.set_status("Warte auf Abschluss von Z-Homing...", "warn")
            has_feedback, _z_after_home = self.wait_for_z_feedback(timeout_s=12.0, poll_interval_s=0.2)
            if not has_feedback:
                logging.error("No Z feedback received after homing")
                self.set_status("Fehler: Keine Z-Rueckmeldung nach Z-Homing", "error")
                self.z_is_zero = False
                self.update_xy_home_lock_state(refresh_z_position=False)
                return False

        current_z = moonraker.get_current_z_position()
        if current_z is not None and abs(current_z) <= self.z_zero_tolerance:
            self.z_is_zero = True
            self.update_xy_home_lock_state(refresh_z_position=False)
            if requires_reference:
                logging.info("Z homed and already at Z0")
                self.set_status("Z-Sicherheitssequenz abgeschlossen (Z homed + Z0)", "success")
            else:
                self.set_status("Z bereits auf 0", "info")
            return True

        if current_z is None:
            self.z_is_zero = False
            self.update_xy_home_lock_state(refresh_z_position=False)
            logging.error("Could not verify current Z position")
            self.set_status("Fehler: Z-Position konnte nicht gelesen werden", "error")
            return False

        self.set_status("Sicherheitssequenz: Z auf 0 fahren...", "warn")
        if not moonraker.send_gcode(f"G1 F{self._fmt_number(self.z_move_speed)}"):
            logging.error("Failed to set Z move speed")
            self.set_status("Fehler: Z-Geschwindigkeit konnte nicht gesetzt werden", "error")
            return False

        if not moonraker.send_gcode("G1 Z0", timeout_s=25.0):
            logging.error("Failed to move Z to 0")
            self.set_status("Fehler: Z konnte nicht auf 0 fahren", "error")
            self.z_is_zero = False
            self.update_xy_home_lock_state(refresh_z_position=False)
            return False

        self.set_status("Warte bis Z=0 erreicht ist...", "warn")
        reached_zero, verify_z = self.wait_for_z_target(target=0.0, timeout_s=15.0, poll_interval_s=0.2, settle_time_s=0.3)
        if not reached_zero:
            if verify_z is None:
                logging.error("Could not verify Z position after Z0 move")
                self.set_status("Fehler: Z-Position nach Z0 nicht lesbar", "error")
            else:
                logging.error(f"Z verification failed after Z0 move timeout: Z={verify_z:.3f}")
                self.set_status(f"Fehler: Z ist nach Fahrt nicht 0 (Z={verify_z:.2f})", "error")
            self.z_is_zero = False
            self.update_xy_home_lock_state(refresh_z_position=False)
            return False

        self.z_is_zero = True
        self.update_xy_home_lock_state(refresh_z_position=False)
        logging.info("Z safety sequence complete: Z ready at 0")
        self.set_status("Z-Sicherheitssequenz abgeschlossen (Z0 bestätigt)", "success")
        return True

    def home_axis(self, instance, axis):
        """Home a single axis via Moonraker."""
        axis = str(axis).upper()

        if axis == "Z":
            if self.z_safety_enabled:
                if self.ensure_z_homed_and_zero(force_rehome=True):
                    logging.info("Axis Z homed and moved to Z0")
                    self.set_status("Z gehomed und auf 0 gefahren", "success")
            else:
                if moonraker.send_gcode("G28 Z", timeout_s=45.0):
                    self.z_reference_known = True
                    self.z_is_zero = False
                    self.update_xy_home_lock_state(refresh_z_position=True)
                    logging.info("Axis Z homed (Z safety disabled)")
                    self.set_status("Z erfolgreich gehomed", "success")
                else:
                    self.set_status("Z-Home fehlgeschlagen", "error")
            return

        if self.z_safety_enabled and axis in ("X", "Y"):
            if not (self.z_reference_known and self.z_is_zero):
                logging.warning(f"Blocked {axis} home: Z not homed and at 0")
                self.update_xy_home_lock_state(refresh_z_position=True)
                self.set_status(f"{axis}-Home gesperrt: erst Z homen und auf 0 fahren", "warn")
                return

        command = f"G28 {axis}"
        if moonraker.send_gcode(command):
            logging.info(f"Axis {axis} homed after mandatory Z safety sequence")
            self.set_status(f"{axis} erfolgreich gehomed", "success")
        else:
            self.set_status(f"{axis}-Home fehlgeschlagen", "error")

    def home_all_axes(self, instance):
        """Home all axes via Moonraker."""
        if self.z_safety_enabled:
            if not self.ensure_z_homed_and_zero(force_rehome=True):
                logging.error("Blocked X/Y homing because Z safety sequence failed")
                self.set_status("Home gesperrt: Z-Sequenz fehlgeschlagen", "error")
                return

        if moonraker.send_gcode("G28 X Y"):
            if self.z_safety_enabled:
                logging.info("All axes homed with mandatory sequence: Z home -> Z0 -> X/Y home")
                self.set_status("Home fertig: Z -> Z0 -> X/Y", "success")
            else:
                logging.info("X/Y homed (Z safety disabled)")
                self.set_status("Home fertig: X/Y", "success")
        else:
            self.set_status("X/Y Home fehlgeschlagen", "error")

    def move_z_up_to_zero(self, _instance):
        """Move Z to safe position 0 (available only after Z has been homed)."""
        if not self.z_reference_known:
            self.set_status("Z Up gesperrt: erst Z homen", "warn")
            self.update_xy_home_lock_state(refresh_z_position=False)
            return

        if not moonraker.send_gcode("G90"):
            self.set_status("Fehler: G90 konnte nicht gesetzt werden", "error")
            return

        if not moonraker.send_gcode(f"G1 F{self._fmt_number(self.z_move_speed)}"):
            self.set_status("Fehler: Z-Geschwindigkeit konnte nicht gesetzt werden", "error")
            return

        if not moonraker.send_gcode("G1 Z0", timeout_s=25.0):
            self.set_status("Z Up fehlgeschlagen", "error")
            return

        reached_zero, verify_z = self.wait_for_z_target(target=0.0, timeout_s=15.0, poll_interval_s=0.2, settle_time_s=0.3)
        if not reached_zero:
            self.z_is_zero = False
            self.update_xy_home_lock_state(refresh_z_position=False)
            if verify_z is None:
                self.set_status("Fehler: Z-Position nach Z Up nicht lesbar", "error")
            else:
                self.set_status(f"Fehler: Z ist nicht auf 0 (Z={verify_z:.2f})", "error")
            return

        self.z_is_zero = True
        self.update_xy_home_lock_state(refresh_z_position=False)
        logging.info("Z moved to position 0 via Z Up")
        self.set_status("Z auf Position 0", "success")

    def move_z_down_to_endstop(self, _instance):
        """Move Z to the maximum endstop reference."""
        if not self.z_reference_known:
            self.set_status("Z Down gesperrt: erst Z homen", "warn")
            self.update_xy_home_lock_state(refresh_z_position=False)
            return

        if not moonraker.send_gcode("G90"):
            self.set_status("Fehler: G90 konnte nicht gesetzt werden", "error")
            return

        if not moonraker.send_gcode("G28 Z", timeout_s=45.0):
            self.set_status("Z Down fehlgeschlagen", "error")
            return

        has_feedback, current_z = self.wait_for_z_feedback(timeout_s=12.0, poll_interval_s=0.2)
        if not has_feedback:
            self.z_is_zero = False
            self.update_xy_home_lock_state(refresh_z_position=False)
            self.set_status("Fehler: Keine Z-Rueckmeldung nach Z Down", "error")
            return

        self.z_reference_known = True
        self.z_is_zero = abs(current_z) <= self.z_zero_tolerance
        self.update_xy_home_lock_state(refresh_z_position=False)
        logging.info(f"Z moved to endstop via Z Down (Z={current_z:.3f})")
        self.set_status("Z auf Endstop gefahren", "success")

    def disable_motors(self, instance):
        """Disable stepper motors (holding current off)."""
        if moonraker.send_gcode("M18"):
            self.z_reference_known = False
            self.z_is_zero = False
            self.update_xy_home_lock_state(refresh_z_position=False)
            logging.info("Motors disabled (holding current off)")
            self.set_status("Motoren deaktiviert", "info")
        else:
            self.set_status("Motoren konnten nicht deaktiviert werden", "error")

    def load_positions(self):
        """Load positions from JSON with error handling."""
        defaults = self.default_slot_positions()
        loaded_data = {}
        if os.path.exists("positions.json"):
            try:
                with open("positions.json", "r") as f:
                    loaded_data = json.load(f)
            except json.JSONDecodeError:
                logging.error("positions.json is corrupted")

        if not isinstance(loaded_data, dict):
            loaded_data = {}

        normalized = {}
        for index in range(1, 16):
            key = str(index)
            default_pos = defaults[key]
            raw_pos = loaded_data.get(key, {}) if isinstance(loaded_data.get(key, {}), dict) else {}

            try:
                x_value = self._parse_float(raw_pos.get("x", default_pos["x"]))
            except (TypeError, ValueError):
                x_value = default_pos["x"]

            try:
                y_value = self._parse_float(raw_pos.get("y", default_pos["y"]))
            except (TypeError, ValueError):
                y_value = default_pos["y"]

            try:
                speed_value = self._clamp_speed(raw_pos.get("speed", default_pos["speed"]))
            except (TypeError, ValueError):
                speed_value = default_pos["speed"]

            normalized[key] = {
                "x": x_value,
                "y": y_value,
                "speed": speed_value
            }

        return normalized

    def store_positions(self):
        """Store positions to JSON with error handling."""
        try:
            with open("positions.json", "w") as f:
                json.dump(self.positions, f, indent=4)
            logging.info("Positions saved")
        except IOError as e:
            logging.error(f"Error saving positions: {e}")


class SyringeCalibrationPopup(Popup):
    def __init__(self, syringe_screen, **kwargs):
        super().__init__(**kwargs)
        self.syringe_screen = syringe_screen
        self.title = "Spritzen-Kalibration"
        self.size_hint = (0.86, 0.9)
        self.auto_dismiss = False
        self.z_move_speed = float(CONFIG.get('z_move_speed_mm_min', 1200.0))
        self.z_zero_tolerance_mm = float(CONFIG.get('z_zero_tolerance_mm', 0.15))
        self.z_settle_time_s = float(CONFIG.get('z_settle_time_s', 1.0))
        self.z_wait_timeout_s = float(CONFIG.get('z_wait_timeout_s', 180.0))
        self.calibration_dwell_s = float(CONFIG.get('calibration_dwell_s', 10.0))
        self.calibration_final_draw_mm = float(CONFIG.get('calibration_final_draw_mm', 2.0))
        self.travel_distances = (30.0, 80.0, 140.0)
        self.measure_inputs = {}
        self.output_buttons = {}

        root = BoxLayout(orientation='vertical', padding=[16, 16, 16, 16], spacing=10)
        root.add_widget(Label(
            text="Messwert (ml) über dem jeweiligen Kalibrations-Button eingeben.",
            size_hint_y=None,
            height=32,
            font_size=16,
            halign='left',
            valign='middle'
        ))

        calibrations_row = BoxLayout(orientation='horizontal', size_hint=(1, 1), spacing=12)
        for travel_mm in self.travel_distances:
            col = BoxLayout(orientation='vertical', spacing=8)
            measure_input = TextInput(
                hint_text=f"Gemessen bei {int(travel_mm)} mm (ml)",
                multiline=False,
                input_filter='float',
                size_hint_y=None,
                height=48,
                font_size=18
            )
            calib_btn = Button(text=f"{int(travel_mm)} mm", size_hint_y=None, height=58, font_size=20)
            calib_btn.bind(on_press=lambda _btn, t=travel_mm: self.run_calibration(t))

            output_btn = Button(text="Ausgabe", size_hint_y=None, height=54, font_size=18, disabled=True, opacity=0)
            output_btn.bind(on_press=lambda _btn, t=travel_mm: self.run_output(t))

            col.add_widget(measure_input)
            col.add_widget(calib_btn)
            col.add_widget(output_btn)
            calibrations_row.add_widget(col)

            self.measure_inputs[travel_mm] = measure_input
            self.output_buttons[travel_mm] = output_btn

        root.add_widget(calibrations_row)

        self.status_label = Label(
            text="Bereit",
            size_hint_y=None,
            height=34,
            font_size=16,
            color=[0.9, 0.95, 1, 1],
            halign='left',
            valign='middle'
        )
        self.status_label.bind(size=lambda inst, _v: setattr(inst, 'text_size', inst.size))
        root.add_widget(self.status_label)

        action_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=60, spacing=12)
        self.calculate_btn = Button(text="Berechnen", font_size=20, disabled=True)
        close_btn = Button(text="Schließen", font_size=20)
        self.calculate_btn.bind(on_press=self.calculate_slope)
        close_btn.bind(on_press=lambda _btn: self.dismiss())
        action_row.add_widget(self.calculate_btn)
        action_row.add_widget(close_btn)
        root.add_widget(action_row)

        self.content = root

        for measure_input in self.measure_inputs.values():
            measure_input.bind(text=lambda *_args: self._update_calculate_button_state())
        self._update_calculate_button_state()

    def _update_calculate_button_state(self):
        all_filled = all(str(inp.text).strip() for inp in self.measure_inputs.values())
        self.calculate_btn.disabled = not all_filled

    def _set_status(self, message):
        self.status_label.text = message
        logging.info(f"Syringe calibration: {message}")

    def _send_gcode(self, command, error_message, timeout_s=None):
        if moonraker.send_gcode(command, timeout_s=timeout_s):
            return True
        self._set_status(error_message)
        logging.error(f"Calibration command failed: {command}")
        return False

    def _parse_decimal(self, text):
        normalized = str(text).strip().replace(',', '.')
        if not normalized:
            raise ValueError("empty")
        return float(normalized)

    def _draw_relative_mm(self, draw_distance_mm, error_message):
        current = self.syringe_screen.syringe_position_mm
        target = self.syringe_screen._clamp_syringe_target(current + float(draw_distance_mm))
        if abs(target - current) < 1e-6:
            self._set_status("Spritzenweg begrenzt: Grenze erreicht")
            return False
        return self.syringe_screen._move_to_position(target, error_message)

    def _wait_for_z_target(self, target_z=0.0, timeout_s=None, poll_interval_s=0.25):
        deadline = time.monotonic() + (self.z_wait_timeout_s if timeout_s is None else float(timeout_s))
        settle_since = None
        target_value = float(target_z)

        while time.monotonic() < deadline:
            z_value = moonraker.get_current_z_position()
            if z_value is None:
                settle_since = None
                time.sleep(poll_interval_s)
                continue

            if abs(float(z_value) - target_value) <= self.z_zero_tolerance_mm:
                if settle_since is None:
                    settle_since = time.monotonic()
                elif time.monotonic() - settle_since >= self.z_settle_time_s:
                    return True
            else:
                settle_since = None

            time.sleep(poll_interval_s)

        return False

    def _move_z_to_zero(self):
        if not self._send_gcode("G90", "Fehler: G90 konnte nicht gesetzt werden"):
            return False
        if not self._send_gcode(f"G1 F{self.z_move_speed:.0f}", "Fehler: Z-Geschwindigkeit konnte nicht gesetzt werden"):
            return False
        if not self._send_gcode("G1 Z0", "Fehler: Z konnte nicht auf 0 fahren", timeout_s=max(90.0, self.z_wait_timeout_s)):
            return False

        if not self._send_gcode(
            "M400",
            "Fehler: Z-Bewegung konnte nicht abgeschlossen werden",
            timeout_s=max(90.0, self.z_wait_timeout_s)
        ):
            return False

        if not self._wait_for_z_target(target_z=0.0, timeout_s=self.z_wait_timeout_s):
            self._set_status("Fehler: Z hat Position 0 nicht rechtzeitig erreicht")
            return False
        return True

    def _move_z_to_endstop(self):
        if not self._send_gcode("G90", "Fehler: G90 konnte nicht gesetzt werden"):
            return False
        if not self._send_gcode("G28 Z", "Fehler: Z konnte nicht referenziert werden", timeout_s=45.0):
            return False
        return True

    def run_calibration(self, travel_mm):
        draw_sign = -self.syringe_screen._home_search_sign()
        self._set_status(f"Kalibration {int(travel_mm)} mm startet...")

        if not self.syringe_screen._send_syringe_command(
            "MANUAL_STEPPER STEPPER=syringe ENABLE=1",
            "Fehler: Spritze konnte nicht aktiviert werden"
        ):
            self._set_status("Fehler: Spritze konnte nicht aktiviert werden")
            return

        if not self._move_z_to_zero():
            return

        if not self._draw_relative_mm(draw_sign * 10.0, "Fehler: 10 mm Vorzug fehlgeschlagen"):
            self._set_status("Fehler: Vorzug fehlgeschlagen")
            return

        if not self._move_z_to_endstop():
            return

        if not self._draw_relative_mm(draw_sign * float(travel_mm), f"Fehler: Aufziehen {int(travel_mm)} mm fehlgeschlagen"):
            self._set_status(f"Fehler: Aufziehen {int(travel_mm)} mm fehlgeschlagen")
            return

        self._set_status(f"Warte {self.calibration_dwell_s:.0f}s nach Aufziehen {int(travel_mm)} mm...")
        time.sleep(max(0.0, self.calibration_dwell_s))

        if not self._move_z_to_zero():
            return

        if not self._draw_relative_mm(
            draw_sign * self.calibration_final_draw_mm,
            f"Fehler: Zusatz-Aufziehen {self.calibration_final_draw_mm:.1f} mm fehlgeschlagen"
        ):
            self._set_status(f"Fehler: Zusatz-Aufziehen {self.calibration_final_draw_mm:.1f} mm fehlgeschlagen")
            return

        for btn in self.output_buttons.values():
            btn.disabled = True
            btn.opacity = 0

        active_output_btn = self.output_buttons[travel_mm]
        active_output_btn.disabled = False
        active_output_btn.opacity = 1
        self._set_status(f"Kalibration {int(travel_mm)} mm fertig. Jetzt Ausgabe drücken.")

    def run_output(self, travel_mm):
        # Fully empty by driving syringe to its configured endstop reference.
        if not self.syringe_screen.home_syringe(None):
            self._set_status("Fehler: Ausgabe fehlgeschlagen (Endschalter nicht erreicht)")
            return

        btn = self.output_buttons[travel_mm]
        btn.disabled = True
        btn.opacity = 0
        self._set_status(f"Ausgabe für {int(travel_mm)} mm abgeschlossen (Spritze am Endschalter)")

    def calculate_slope(self, _instance):
        measured_values = {}
        for travel_mm in self.travel_distances:
            raw_text = self.measure_inputs[travel_mm].text
            try:
                measured = self._parse_decimal(raw_text)
            except ValueError:
                self._set_status("Bitte alle drei Volumenwerte als Dezimalzahl eintragen")
                return
            if measured <= 0:
                self._set_status("Volumenwerte müssen größer als 0 sein")
                return
            measured_values[travel_mm] = measured

        numerator = sum(distance * measured_values[distance] for distance in self.travel_distances)
        denominator = sum(distance * distance for distance in self.travel_distances)
        if denominator <= 0:
            self._set_status("Fehler bei Steigungsberechnung")
            return

        slope_ml_per_mm = numerator / denominator
        if slope_ml_per_mm <= 0:
            self._set_status("Ungültige Steigung berechnet")
            return

        global SYRINGE_CALIBRATION_DATA
        SYRINGE_CALIBRATION_DATA = {
            'slope_ml_per_mm': slope_ml_per_mm,
            'mm_per_ml': 1.0 / slope_ml_per_mm,
            'points': {
                '30': measured_values[30.0],
                '80': measured_values[80.0],
                '140': measured_values[140.0]
            }
        }

        if not save_syringe_calibration_data(SYRINGE_CALIBRATION_DATA):
            self._set_status("Steigung berechnet, aber Speichern in calibration.json fehlgeschlagen")
            return

        self._set_status(
            f"Steigung gespeichert (calibration.json): {slope_ml_per_mm:.6f} ml/mm | "
            f"Umrechnung: {SYRINGE_CALIBRATION_DATA['mm_per_ml']:.6f} mm/ml"
        )


class SyringeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.syringe_speed_mm_s = float(CONFIG.get('syringe_speed_mm_s', 5.0))
        self.syringe_accel_mm_s2 = float(CONFIG.get('syringe_accel_mm_s2', 2.0))
        self.syringe_min_pos_mm = float(CONFIG.get('syringe_min_pos_mm', -200.0))
        self.syringe_max_pos_mm = float(CONFIG.get('syringe_max_pos_mm', 200.0))
        self.syringe_home_coarse_mm = float(CONFIG.get('syringe_home_coarse_mm', 170.0))
        self.syringe_home_backoff_mm = float(CONFIG.get('syringe_home_backoff_mm', 2.0))
        self.syringe_home_fine_mm = float(CONFIG.get('syringe_home_fine_mm', 5.0))
        self.syringe_home_two_stage = bool(CONFIG.get('syringe_home_two_stage', True))
        self.syringe_home_direction = str(CONFIG.get('syringe_home_direction', 'max')).lower()
        self.syringe_position_mm = float(CONFIG.get('syringe_start_pos_mm', 0.0))
        self.syringe_timeout_buffer_s = float(CONFIG.get('syringe_timeout_buffer_s', 25.0))
        self.syringe_output_speed_factor = float(CONFIG.get('syringe_output_speed_factor', 0.5))
        self.calibration_popup = None

        root = BoxLayout(orientation='vertical', padding=[20, 20, 20, 20], spacing=16)

        root.add_widget(Label(
            text="Spritze",
            size_hint_y=None,
            height=46,
            font_size=24,
            color=[1, 1, 1, 1]
        ))

        motion_info = Label(
            text=(
                f"TR8x2 langsam: {self.syringe_speed_mm_s:.2f} mm/s | "
                f"Ramp: {self.syringe_accel_mm_s2:.2f} mm/s² | "
                f"Range: {self.syringe_min_pos_mm:.0f}..{self.syringe_max_pos_mm:.0f}"
            ),
            size_hint_y=None,
            height=28,
            font_size=15,
            color=[0.82, 0.9, 1, 1],
            halign='left',
            valign='middle'
        )
        motion_info.bind(size=lambda inst, _v: setattr(inst, 'text_size', inst.size))
        root.add_widget(motion_info)

        home_anchor = AnchorLayout(anchor_x='left', anchor_y='top', size_hint=(1, None), height=80)
        home_btn = Button(
            text="Home",
            size_hint=(None, None),
            size=(200, 66),
            font_size=22
        )
        home_btn.bind(on_press=self.home_syringe)
        home_anchor.add_widget(home_btn)
        root.add_widget(home_anchor)

        forward_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=72, spacing=12)
        forward_row.add_widget(Label(text="Vor", size_hint=(None, 1), width=90, font_size=20))
        for step in (1, 5, 10):
            step_btn = Button(text=f"+{step} mm", font_size=18)
            step_btn.bind(on_press=lambda _btn, distance=-step: self.move_syringe_mm(distance))
            forward_row.add_widget(step_btn)
        root.add_widget(forward_row)

        backward_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=72, spacing=12)
        backward_row.add_widget(Label(text="Zurück", size_hint=(None, 1), width=90, font_size=20))
        for step in (1, 5, 10):
            step_btn = Button(text=f"-{step} mm", font_size=18)
            step_btn.bind(on_press=lambda _btn, distance=step: self.move_syringe_mm(distance))
            backward_row.add_widget(step_btn)
        root.add_widget(backward_row)

        diag_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=72, spacing=12)
        calibration_btn = Button(text="Kalibration", font_size=20)
        enable_btn = Button(text="Enable", font_size=20)
        dump_tmc_btn = Button(text="Dump TMC", font_size=20)

        calibration_btn.bind(on_press=self.open_calibration_window)
        enable_btn.bind(on_press=self.enable_syringe_stepper)
        dump_tmc_btn.bind(on_press=self.dump_tmc_syringe)

        diag_row.add_widget(calibration_btn)
        diag_row.add_widget(enable_btn)
        diag_row.add_widget(dump_tmc_btn)
        root.add_widget(diag_row)

        root.add_widget(Widget())

        self.add_widget(root)

    def open_calibration_window(self, _instance):
        self.calibration_popup = SyringeCalibrationPopup(self)
        self.calibration_popup.open()

    def _log_syringe_status(self, message):
        logging.info(f"Syringe status: {message}")

    def _send_syringe_command(self, command, error_message, timeout_s=None):
        effective_timeout = timeout_s
        if effective_timeout is None:
            effective_timeout = max(12.0, float(self.syringe_timeout_buffer_s))

        if moonraker.send_gcode(command, timeout_s=effective_timeout):
            return True
        self._log_syringe_status(error_message)
        logging.error(f"Syringe command failed: {command}")
        return False

    def _estimate_syringe_move_timeout(self, start_pos_mm, target_pos_mm, speed_mm_s=None, extra_s=None):
        distance_mm = abs(float(target_pos_mm) - float(start_pos_mm))
        speed_value = self.syringe_speed_mm_s if speed_mm_s is None else float(speed_mm_s)
        speed_value = max(0.1, speed_value)
        buffer_s = self.syringe_timeout_buffer_s if extra_s is None else float(extra_s)
        move_time_s = distance_mm / speed_value
        return max(12.0, move_time_s + max(8.0, buffer_s))

    def _clamp_syringe_target(self, target_mm):
        return max(self.syringe_min_pos_mm, min(float(target_mm), self.syringe_max_pos_mm))

    def _home_search_sign(self):
        return 1.0 if self.syringe_home_direction == 'max' else -1.0

    def _sync_syringe_position(self, error_message):
        return self._send_syringe_command(
            f"MANUAL_STEPPER STEPPER=syringe SET_POSITION={self.syringe_position_mm:.3f}",
            error_message,
            timeout_s=max(30.0, float(self.syringe_timeout_buffer_s) * 2.0)
        )

    def _move_to_position(self, target_position, error_message, speed_factor=1.0, timeout_extra_s=None):
        clamped_target = self._clamp_syringe_target(target_position)
        effective_speed = max(0.1, self.syringe_speed_mm_s * max(0.05, float(speed_factor)))
        timeout_s = self._estimate_syringe_move_timeout(
            self.syringe_position_mm,
            clamped_target,
            speed_mm_s=effective_speed,
            extra_s=timeout_extra_s
        )
        if not self._sync_syringe_position("Fehler: Spritzenposition konnte nicht synchronisiert werden"):
            return False
        if not self._send_syringe_command(
            (
                f"MANUAL_STEPPER STEPPER=syringe MOVE={clamped_target:.3f} "
                f"SPEED={effective_speed:.3f} ACCEL={self.syringe_accel_mm_s2:.3f}"
            ),
            error_message,
            timeout_s=timeout_s
        ):
            return False

        self.syringe_position_mm = clamped_target
        return True

    def _run_home_move(self, target_mm, error_message):
        timeout_s = self._estimate_syringe_move_timeout(
            self.syringe_position_mm,
            target_mm,
            speed_mm_s=self.syringe_speed_mm_s,
            extra_s=max(self.syringe_timeout_buffer_s, 30.0)
        )
        return self._send_syringe_command(
            (
                f"MANUAL_STEPPER STEPPER=syringe MOVE={target_mm:.3f} "
                f"SPEED={self.syringe_speed_mm_s:.3f} ACCEL={self.syringe_accel_mm_s2:.3f} STOP_ON_ENDSTOP=1"
            ),
            error_message,
            timeout_s=timeout_s
        )

    def home_syringe(self, _instance):
        if not self._send_syringe_command(
            "MANUAL_STEPPER STEPPER=syringe ENABLE=1",
            "Fehler: Spritze konnte nicht aktiviert werden"
        ):
            return False

        if not self._send_syringe_command(
            "MANUAL_STEPPER STEPPER=syringe SET_POSITION=0",
            "Fehler: Spritzenposition konnte nicht gesetzt werden"
        ):
            return False

        self.syringe_position_mm = 0.0
        home_sign = self._home_search_sign()
        coarse_target = self._clamp_syringe_target(home_sign * abs(self.syringe_home_coarse_mm))

        if not self._run_home_move(coarse_target, "Fehler: Grob-Home fehlgeschlagen"):
            return False

        if not self._send_syringe_command(
            "MANUAL_STEPPER STEPPER=syringe SET_POSITION=0",
            "Fehler: Home-Position konnte nicht gesetzt werden"
        ):
            return False

        if self.syringe_home_two_stage:
            backoff_target = self._clamp_syringe_target(-home_sign * abs(self.syringe_home_backoff_mm))
            if not self._send_syringe_command(
                (
                    f"MANUAL_STEPPER STEPPER=syringe MOVE={backoff_target:.3f} "
                    f"SPEED={self.syringe_speed_mm_s:.3f} ACCEL={self.syringe_accel_mm_s2:.3f}"
                ),
                "Fehler: Home-Backoff fehlgeschlagen"
            ):
                return False

            if not self._send_syringe_command(
                "MANUAL_STEPPER STEPPER=syringe SET_POSITION=0",
                "Fehler: Backoff-Position konnte nicht gesetzt werden"
            ):
                return False

            fine_target = self._clamp_syringe_target(home_sign * abs(self.syringe_home_fine_mm))
            if not self._run_home_move(fine_target, "Fehler: Fein-Home fehlgeschlagen"):
                return False

            if not self._send_syringe_command(
                "MANUAL_STEPPER STEPPER=syringe SET_POSITION=0",
                "Fehler: Fein-Home-Position konnte nicht gesetzt werden"
            ):
                return False

        self.syringe_position_mm = 0.0
        self._log_syringe_status("Spritze gehomed (Grob + Fein)" if self.syringe_home_two_stage else "Spritze gehomed")
        logging.info("Syringe homed with manual_stepper coarse/fine sequence")
        return True

    def reference_syringe(self, _instance):
        if not self.home_syringe(_instance):
            return

        max_draw_target = self.syringe_max_pos_mm if self.syringe_home_direction == 'min' else self.syringe_min_pos_mm
        if not self._move_to_position(max_draw_target, "Fehler: Max-Aufziehen fehlgeschlagen"):
            return

        if not self._move_to_position(0.0, "Fehler: Rückfahrt zu 0 fehlgeschlagen"):
            return

        self._log_syringe_status("Referenzieren fertig: Home -> Max aufziehen -> 0")

    def move_syringe_mm(self, distance_mm):
        if not self._send_syringe_command(
            "MANUAL_STEPPER STEPPER=syringe ENABLE=1",
            "Fehler: Spritze konnte nicht aktiviert werden"
        ):
            return

        if not self._sync_syringe_position("Fehler: Spritzenposition konnte nicht synchronisiert werden"):
            return

        target_position = self._clamp_syringe_target(self.syringe_position_mm + float(distance_mm))
        if abs(target_position - self.syringe_position_mm) < 1e-6:
            self._log_syringe_status("Grenze erreicht: keine weitere Bewegung möglich")
            return

        timeout_s = self._estimate_syringe_move_timeout(
            self.syringe_position_mm,
            target_position,
            speed_mm_s=self.syringe_speed_mm_s,
            extra_s=self.syringe_timeout_buffer_s
        )

        if not self._send_syringe_command(
            (
                f"MANUAL_STEPPER STEPPER=syringe MOVE={target_position:.3f} "
                f"SPEED={self.syringe_speed_mm_s:.3f} ACCEL={self.syringe_accel_mm_s2:.3f}"
            ),
            "Fehler: Spritze konnte nicht bewegt werden",
            timeout_s=timeout_s
        ):
            return

        moved_distance = target_position - self.syringe_position_mm
        self.syringe_position_mm = target_position
        direction_text = "vor" if moved_distance > 0 else "zurück"
        self._log_syringe_status(f"Spritze {direction_text}: {abs(moved_distance):.1f} mm")
        logging.info(f"Syringe moved {moved_distance} mm to target {target_position} mm")

    def query_endstops(self, _instance):
        self._log_syringe_status("Abfrage läuft")
        if not moonraker.send_gcode("QUERY_ENDSTOPS"):
            self._log_syringe_status("Fehler: QUERY_ENDSTOPS fehlgeschlagen")
            logging.error("QUERY_ENDSTOPS failed")
            return

        lines = moonraker.get_console_lines(count=20)
        relevant = [l for l in lines if 'endstop' in l.lower() or 'QUERY' in l]
        display_text = " | ".join(relevant) if relevant else " | ".join(lines[-10:])
        self._log_syringe_status(display_text)
        logging.info("QUERY_ENDSTOPS result displayed")

    def enable_syringe_stepper(self, _instance):
        if self._send_syringe_command(
            "MANUAL_STEPPER STEPPER=syringe ENABLE=1",
            "Fehler: ENABLE fehlgeschlagen"
        ):
            self._log_syringe_status("Spritze aktiviert (ENABLE=1)")
            logging.info("Syringe stepper enabled")

    def dump_tmc_syringe(self, _instance):
        self._log_syringe_status("DUMP_TMC läuft")
        if not self._send_syringe_command(
            "DUMP_TMC STEPPER=syringe",
            "Fehler: DUMP_TMC fehlgeschlagen"
        ):
            return

        lines = moonraker.get_console_lines(count=40)
        relevant = [
            line for line in lines
            if 'tmc' in line.lower() or 'driver' in line.lower() or 'syringe' in line.lower()
        ]
        display_text = " | ".join(relevant[-12:]) if relevant else "DUMP_TMC gesendet"
        self._log_syringe_status(display_text)
        logging.info("DUMP_TMC result displayed")


class FanCurveGraph(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.window_seconds = 500.0
        self.start_monotonic = time.monotonic()
        self.history = []
        self.bind(pos=self.redraw, size=self.redraw)
        Clock.schedule_once(lambda _dt: self.redraw(), 0)

    def add_pwm_sample(self, pwm_percent):
        elapsed = time.monotonic() - self.start_monotonic
        pwm_value = max(0.0, min(float(pwm_percent), 100.0))
        self.history.append((elapsed, pwm_value))

        window_start, _window_end = self.get_window_range_seconds(now_elapsed=elapsed)
        self.history = [(t, p) for t, p in self.history if t >= window_start]
        self.redraw()

    def get_window_range_seconds(self, now_elapsed=None):
        if now_elapsed is None:
            now_elapsed = time.monotonic() - self.start_monotonic
        window_end = max(self.window_seconds, float(now_elapsed))
        window_start = max(0.0, window_end - self.window_seconds)
        return window_start, window_end

    def _graph_bounds(self):
        pad_x = dp(22)
        pad_y = dp(18)
        left = self.x + pad_x
        right = self.right - pad_x
        bottom = self.y + pad_y
        top = self.top - pad_y
        return left, right, bottom, top

    def _time_to_x(self, elapsed_seconds, window_start, window_end):
        left, right, _, _ = self._graph_bounds()
        t = max(window_start, min(float(elapsed_seconds), window_end))
        if window_end <= window_start:
            return left
        return left + (t - window_start) / (window_end - window_start) * (right - left)

    def _pwm_to_y(self, pwm_percent):
        _, _, bottom, top = self._graph_bounds()
        pwm = max(0.0, min(float(pwm_percent), 100.0))
        return bottom + pwm / 100.0 * (top - bottom)

    def redraw(self, *_args):
        if self.width <= 0 or self.height <= 0:
            return

        left, right, bottom, top = self._graph_bounds()
        now_elapsed = time.monotonic() - self.start_monotonic
        window_start, window_end = self.get_window_range_seconds(now_elapsed=now_elapsed)
        self.canvas.clear()

        with self.canvas:
            Color(0.08, 0.11, 0.15, 0.85)
            Rectangle(pos=self.pos, size=self.size)

            Color(0.22, 0.28, 0.35, 1)
            for grid_step in [0, 25, 50, 75, 100]:
                y_pos = self._pwm_to_y(grid_step)
                Line(points=[left, y_pos, right, y_pos], width=1)

            for marker in range(0, 501, 100):
                t_marker = window_start + marker
                x_pos = self._time_to_x(t_marker, window_start, window_end)
                Line(points=[x_pos, bottom, x_pos, top], width=1)

            Color(0.5, 0.66, 0.82, 1)
            visible_points = []
            for elapsed, pwm in self.history:
                if window_start <= elapsed <= window_end:
                    visible_points.extend([self._time_to_x(elapsed, window_start, window_end), self._pwm_to_y(pwm)])

            if len(visible_points) >= 4:
                Line(points=visible_points, width=2)
            elif len(visible_points) == 2:
                px, py = visible_points
                Ellipse(pos=(px - dp(3), py - dp(3)), size=(dp(6), dp(6)))

            Color(0.65, 0.75, 0.85, 1)
            Line(points=[left, bottom, left, top], width=1.4)
            Line(points=[left, bottom, right, bottom], width=1.4)


class LuefterScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._refresh_event = None

        root = BoxLayout(orientation='vertical', padding=[14, 10, 14, 12], spacing=10)

        title = Label(text="Lüftersteuerung", size_hint_y=None, height=44, font_size=24, color=[1, 1, 1, 1])
        root.add_widget(title)

        axis_info = Label(text="X: Zeit (s)   |   Y: PWM Power (%)", size_hint_y=None, height=24, font_size=14, color=[0.78, 0.9, 1, 1])
        root.add_widget(axis_info)

        graph_row = BoxLayout(orientation='horizontal', size_hint=(1, 0.56), spacing=8)
        y_axis_labels = BoxLayout(orientation='vertical', size_hint=(None, 1), width=44)
        y_axis_labels.add_widget(Label(text="100", font_size=13, color=[0.75, 0.88, 1, 1]))
        y_axis_labels.add_widget(Label(text="50", font_size=13, color=[0.75, 0.88, 1, 1]))
        y_axis_labels.add_widget(Label(text="0", font_size=13, color=[0.75, 0.88, 1, 1]))
        graph_row.add_widget(y_axis_labels)

        self.fan_graph = FanCurveGraph(size_hint=(1, 1))
        graph_row.add_widget(self.fan_graph)
        root.add_widget(graph_row)

        x_axis_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=24, padding=[52, 0, 0, 0])
        self.x_axis_start_label = Label(text="0 s", halign='left', valign='middle', font_size=13, color=[0.75, 0.88, 1, 1])
        self.x_axis_start_label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
        self.x_axis_end_label = Label(text="500 s", halign='right', valign='middle', font_size=13, color=[0.75, 0.88, 1, 1])
        self.x_axis_end_label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
        x_axis_row.add_widget(self.x_axis_start_label)
        x_axis_row.add_widget(self.x_axis_end_label)
        root.add_widget(x_axis_row)

        pwm_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=44, spacing=8)
        pwm_row.add_widget(Label(text="PWM", size_hint=(None, 1), width=54, font_size=16))

        self.pwm_slider = Slider(min=0, max=100, value=65, step=1)
        self.pwm_slider.bind(value=self.on_pwm_slider_change)
        pwm_row.add_widget(self.pwm_slider)

        self.pwm_value_label = Label(text="35 %", size_hint=(None, 1), width=70, font_size=16)
        pwm_row.add_widget(self.pwm_value_label)
        root.add_widget(pwm_row)

        btn_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=56, spacing=10)
        fan_off_btn = Button(text="Aus", font_size=18)
        fan_on_btn = Button(text="Ein", font_size=18)
        set_pwm_btn = Button(text="PWM setzen", font_size=18)

        fan_off_btn.bind(on_press=self.fan_off)
        fan_on_btn.bind(on_press=self.fan_on)
        set_pwm_btn.bind(on_press=self.apply_pwm)

        btn_row.add_widget(fan_off_btn)
        btn_row.add_widget(fan_on_btn)
        btn_row.add_widget(set_pwm_btn)
        root.add_widget(btn_row)

        self.status_label = Label(text="", size_hint_y=None, height=30, font_size=14, color=[1, 1, 1, 0.9])
        root.add_widget(self.status_label)

        self.add_widget(root)
        self.on_pwm_slider_change(self.pwm_slider, self.pwm_slider.value)
        self.update_pwm_graph()

    def on_pre_enter(self, *args):
        self.update_pwm_graph()
        if self._refresh_event is None:
            self._refresh_event = Clock.schedule_interval(lambda _dt: self.update_pwm_graph(), 1.5)
        return super().on_pre_enter(*args)

    def on_leave(self, *args):
        if self._refresh_event is not None:
            self._refresh_event.cancel()
            self._refresh_event = None
        return super().on_leave(*args)

    def _slider_to_pwm_percent(self, slider_value):
        return max(0, min(100, int(round(slider_value))))

    def on_pwm_slider_change(self, _slider, value):
        pwm_percent = self._slider_to_pwm_percent(value)
        self.pwm_value_label.text = f"{pwm_percent} %"

    def _pwm_percent_to_gcode_value(self, percent):
        percent_value = max(0, min(int(round(percent)), 100))
        return int(round((percent_value / 100.0) * 255.0))

    def fan_on(self, _instance):
        pwm_percent = self._slider_to_pwm_percent(self.pwm_slider.value)
        if pwm_percent == 0:
            pwm_percent = 35
            self.pwm_slider.value = pwm_percent
        self._send_pwm(pwm_percent)

    def fan_off(self, _instance):
        if moonraker.send_gcode("M107"):
            self.status_label.text = "Lüfter ausgeschaltet"
            logging.info("Fan disabled via M107")
            self.fan_graph.add_pwm_sample(0)
        else:
            self.status_label.text = "Fehler: Lüfter konnte nicht ausgeschaltet werden"

    def apply_pwm(self, _instance):
        pwm_percent = self._slider_to_pwm_percent(self.pwm_slider.value)
        self._send_pwm(pwm_percent)

    def _send_pwm(self, pwm_percent):
        gcode_value = self._pwm_percent_to_gcode_value(pwm_percent)
        command = f"M106 S{gcode_value}"
        if moonraker.send_gcode(command):
            self.status_label.text = f"PWM gesetzt: {pwm_percent} %"
            logging.info(f"Fan PWM set to {pwm_percent}% (S{gcode_value})")
            self.fan_graph.add_pwm_sample(pwm_percent)
        else:
            self.status_label.text = "Fehler: PWM konnte nicht gesetzt werden"

    def update_pwm_graph(self):
        pwm_percent = self._slider_to_pwm_percent(self.pwm_slider.value)
        self.fan_graph.add_pwm_sample(pwm_percent)
        start_sec, end_sec = self.fan_graph.get_window_range_seconds()
        self.x_axis_start_label.text = f"{int(start_sec)} s"
        self.x_axis_end_label.text = f"{int(end_sec)} s"



class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ui_font = preferred_ui_font()

        root = BoxLayout(orientation='vertical', padding=[16, 12, 16, 12], spacing=10)

        title = Label(
            text="Cocktail Auswahl",
            size_hint_y=None,
            height=56,
            font_size=34,
            color=[1, 1, 1, 1],
            bold=True
        )
        if self.ui_font:
            title.font_name = self.ui_font
        root.add_widget(title)

        subtitle = Label(
            text="Tippe auf ein Rezept im Cocktail-Tab, hier siehst du alle verfügbaren Drinks.",
            size_hint_y=None,
            height=28,
            font_size=16,
            color=[0.82, 0.9, 1, 1]
        )
        if self.ui_font:
            subtitle.font_name = self.ui_font
        root.add_widget(subtitle)

        self.grid = GridLayout(
            cols=4,
            spacing=[14, 14],
            padding=[8, 6, 8, 6],
            size_hint_y=None
        )
        self.grid.bind(minimum_height=self.grid.setter('height'))

        self.scroll = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
            do_scroll_y=True,
            scroll_type=['content'],
            scroll_distance=dp(8),
            scroll_timeout=250,
            bar_width=dp(6)
        )
        self.scroll.add_widget(self.grid)
        root.add_widget(self.scroll)

        self.status_label = Label(text="", size_hint_y=None, height=26, font_size=14, color=[1, 1, 1, 0.9])
        root.add_widget(self.status_label)

        self.add_widget(root)
        self.populate_cocktail_icons()

    def on_pre_enter(self, *args):
        self.populate_cocktail_icons()
        return super().on_pre_enter(*args)

    def populate_cocktail_icons(self):
        self.grid.clear_widgets()

        if not os.path.isdir(COCKTAILS_ICON_DIR):
            self.status_label.text = f"Kein Ordner gefunden: {COCKTAILS_ICON_DIR}"
            return

        icon_files = sorted(
            [f for f in os.listdir(COCKTAILS_ICON_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
        )

        if not icon_files:
            self.status_label.text = "Keine Cocktail-Icons in Cocktails/128_192 gefunden."
            return

        for icon_file in icon_files:
            card = BoxLayout(
                orientation='vertical',
                size_hint=(None, None),
                size=(170, 242),
                spacing=6,
                padding=[4, 4, 4, 4]
            )

            icon_path = os.path.join(COCKTAILS_ICON_DIR, icon_file)
            cocktail_button = Button(
                text="",
                size_hint=(None, None),
                size=(128, 192),
                pos_hint={'center_x': 0.5},
                background_normal=icon_path,
                background_down=icon_path,
                background_color=(1, 1, 1, 1),
                border=(0, 0, 0, 0)
            )
            cocktail_button.bind(on_release=partial(self.on_cocktail_icon_pressed, cocktail_name=pretty_cocktail_name(icon_file)))

            name_label = Label(
                text=pretty_cocktail_name(icon_file),
                size_hint_y=None,
                height=36,
                font_size=16,
                color=[1, 1, 1, 1],
                halign='center',
                valign='middle'
            )
            name_label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
            if self.ui_font:
                name_label.font_name = self.ui_font

            card.add_widget(cocktail_button)
            card.add_widget(name_label)
            self.grid.add_widget(card)

        self.status_label.text = f"{len(icon_files)} Cocktails geladen"

    def on_cocktail_icon_pressed(self, _instance, cocktail_name):
        self.status_label.text = f"Ausgewählt: {cocktail_name}"

class GCodeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = BoxLayout(orientation='vertical', padding=10, spacing=10)

        self.title_label = Label(text="G-Code Befehle", size_hint_y=None, height=40, font_size=20)
        self.layout.add_widget(self.title_label)

        self.gcode_input = TextInput(
            hint_text="G-Code eingeben, eine Zeile pro Befehl (z.B. G28)",
            multiline=True,
            size_hint=(1, 0.45),
            font_size=16
        )
        self.layout.add_widget(self.gcode_input)

        button_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=50, spacing=10)
        send_btn = Button(text="Senden", font_size=16)
        clear_btn = Button(text="Leeren", font_size=16)
        refresh_console_btn = Button(text="Console aktualisieren", font_size=16)
        send_btn.bind(on_press=self.send_gcode)
        clear_btn.bind(on_press=self.clear_gcode)
        refresh_console_btn.bind(on_press=lambda _btn: self.refresh_console())
        button_row.add_widget(send_btn)
        button_row.add_widget(clear_btn)
        button_row.add_widget(refresh_console_btn)
        self.layout.add_widget(button_row)

        self.console_output = TextInput(
            text="",
            readonly=True,
            multiline=True,
            size_hint=(1, 0.45),
            font_size=14,
            hint_text="Live-Konsole: Moonraker-Antworten erscheinen hier"
        )
        self.layout.add_widget(self.console_output)

        self.status_label = Label(text="", size_hint_y=None, height=40, font_size=14)
        self.layout.add_widget(self.status_label)

        self._console_event = None
        self._last_console_lines = []

        self.add_widget(self.layout)

    def on_pre_enter(self, *args):
        self.refresh_console()
        if self._console_event is None:
            self._console_event = Clock.schedule_interval(lambda _dt: self.refresh_console(), 1.0)
        return super().on_pre_enter(*args)

    def on_leave(self, *args):
        if self._console_event is not None:
            self._console_event.cancel()
            self._console_event = None
        return super().on_leave(*args)

    def refresh_console(self):
        lines = moonraker.get_console_lines(count=60)
        if not lines:
            return

        # Prevent unnecessary redraws if content did not change.
        if lines == self._last_console_lines:
            return

        self._last_console_lines = lines
        self.console_output.text = "\n".join(lines)
        self.console_output.cursor = (0, len(self.console_output._lines))

    def send_gcode(self, instance):
        raw_text = self.gcode_input.text.strip()
        if not raw_text:
            self.status_label.text = "Bitte mindestens einen G-Code Befehl eingeben."
            return

        commands = []
        for line in raw_text.splitlines():
            command = line.strip()
            if not command or command.startswith(';') or command.startswith('#'):
                continue
            commands.append(command)

        if not commands:
            self.status_label.text = "Keine gültigen Befehle gefunden."
            return

        success_count = 0
        for command in commands:
            if moonraker.send_gcode(command):
                success_count += 1
                self.console_output.text += f"\n[SEND] {command}" if self.console_output.text else f"[SEND] {command}"

        self.status_label.text = f"Gesendet: {success_count}/{len(commands)} Befehle"
        # Trigger one immediate refresh so responses such as QUERY_ENDSTOPS show up quickly.
        Clock.schedule_once(lambda _dt: self.refresh_console(), 0.3)

    def clear_gcode(self, instance):
        self.gcode_input.text = ""
        self.status_label.text = ""

class EinstellungScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = FloatLayout()
        layout.add_widget(Label(text="Einstellungen", pos_hint={'center_x': 0.5, 'center_y': 0.5}))
        self.add_widget(layout)

class MainScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
        apply_widget_background(self, 'Schwarz.png')

        self.sidebar_container = AnchorLayout(anchor_y='center', size_hint=(None, 1), width=100)
        self.sidebar = BoxLayout(orientation='vertical', size_hint=(None, None))
        self.sidebar.bind(minimum_height=self.sidebar.setter('height'))

        self.screen_manager = ScreenManager()

        # Home-Screen Button
        home_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('home.64.png'),
            background_down=icon('home.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("home")
        )
        home_lbl = Label(text="Home", size_hint_y=None, height=30)
        home_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        home_box.add_widget(home_btn)
        home_box.add_widget(home_lbl)
        self.sidebar.add_widget(home_box)

        # Motor-Screen Button
        motor_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('motor.64.png'),
            background_down=icon('motor.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("motor")
        )
        motor_lbl = Label(text="Motor", size_hint_y=None, height=30)
        motor_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        motor_box.add_widget(motor_btn)
        motor_box.add_widget(motor_lbl)
        self.sidebar.add_widget(motor_box)

        # Lüfter-Screen Button
        luefter_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('lufter.64.png'),
            background_down=icon('lufter.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("luefter")
        )
        luefter_lbl = Label(text="Lüfter", size_hint_y=None, height=30)
        luefter_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        luefter_box.add_widget(luefter_btn)
        luefter_box.add_widget(luefter_lbl)
        self.sidebar.add_widget(luefter_box)

        # Syringe-Screen Button
        syringe_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('syringe.64.png'),
            background_down=icon('syringe.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("syringe")
        )
        syringe_lbl = Label(text="Spritze", size_hint_y=None, height=30)
        syringe_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        syringe_box.add_widget(syringe_btn)
        syringe_box.add_widget(syringe_lbl)
        self.sidebar.add_widget(syringe_box)

        if ENABLE_COCKTAIL_SCREEN:
            # Cocktail-Screen Button
            cocktail_btn = Button(
                size_hint=(None, None),
                size=(64, 64),
                background_normal=icon('cocktail.64.png'),
                background_down=icon('cocktail.64.png'),
                pos_hint={'center_x': 0.5},
                on_press=lambda x: self.switch_screen("cocktail")
            )
            cocktail_lbl = Label(text="Cocktails", size_hint_y=None, height=30)
            cocktail_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
            cocktail_box.add_widget(cocktail_btn)
            cocktail_box.add_widget(cocktail_lbl)
            self.sidebar.add_widget(cocktail_box)

        # Zubereitung-Screen Button
        prep_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('shaker.64.png'),
            background_down=icon('shaker.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("prep")
        )
        prep_lbl = Label(text="Zubereitung", size_hint_y=None, height=30)
        prep_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        prep_box.add_widget(prep_btn)
        prep_box.add_widget(prep_lbl)
        self.sidebar.add_widget(prep_box)

        # G-Code-Screen Button
        gcode_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('bug.64.png'),
            background_down=icon('bug.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("gcode")
        )
        gcode_lbl = Label(text="G-Code", size_hint_y=None, height=30)
        gcode_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        gcode_box.add_widget(gcode_btn)
        gcode_box.add_widget(gcode_lbl)
        self.sidebar.add_widget(gcode_box)

        # Screens hinzufügen
        if ENABLE_COCKTAIL_SCREEN:
            self.screen_manager.add_widget(CocktailInputScreen(name="cocktail"))
        self.screen_manager.add_widget(PreparationScreen(name="prep"))
        self.screen_manager.add_widget(MotorPositionScreen(name="motor"))
        self.screen_manager.add_widget(LuefterScreen(name="luefter"))
        self.screen_manager.add_widget(SyringeScreen(name="syringe"))
        self.screen_manager.add_widget(HomeScreen(name="home"))
        self.screen_manager.add_widget(GCodeScreen(name="gcode"))

        self.screen_manager.current = "home"
        self.sidebar_container.add_widget(self.sidebar)
        self.add_widget(self.sidebar_container)

        self.add_widget(self.screen_manager)

    def switch_screen(self, name):
        self.screen_manager.current = name

    def _transform_touch_if_needed(self, touch):
        """Rotate touch coordinates for physically rotated displays."""
        if TOUCH_ROTATION % 360 == 0:
            return False

        device_name = str(getattr(touch, 'device', '')).lower()
        if 'mouse' in device_name:
            return False

        width, height = Window.size
        if TOUCH_ROTATION % 360 == 180:
            touch.apply_transform_2d(lambda x, y: (width - x, height - y))
            return True
        if TOUCH_ROTATION % 360 == 90:
            touch.apply_transform_2d(lambda x, y: (y, width - x))
            return True
        if TOUCH_ROTATION % 360 == 270:
            touch.apply_transform_2d(lambda x, y: (height - y, x))
            return True
        return False

    def on_touch_down(self, touch):
        touch.push()
        try:
            self._transform_touch_if_needed(touch)
            return super().on_touch_down(touch)
        finally:
            touch.pop()

    def on_touch_move(self, touch):
        touch.push()
        try:
            self._transform_touch_if_needed(touch)
            return super().on_touch_move(touch)
        finally:
            touch.pop()

    def on_touch_up(self, touch):
        touch.push()
        try:
            self._transform_touch_if_needed(touch)
            return super().on_touch_up(touch)
        finally:
            touch.pop()

class CocktailApp(App):
    def build(self):
        try:
            logging.info(f"Window size={Window.size}, system_size={Window.system_size}, dpi={Window.dpi}")
        except Exception:
            pass
        return MainScreen()

if __name__ == "__main__":
    CocktailApp().run()