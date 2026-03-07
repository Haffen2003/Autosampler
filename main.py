import logging
import json
import os
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
        'icon_dir': 'Icons'
    }

CONFIG = load_config()
MOONRAKER_URL = CONFIG.get('moonraker_url', 'http://localhost:7125')
TOUCH_ROTATION = int(CONFIG.get('touch_rotation', 180))

# base directories for resources
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, CONFIG.get('icon_dir', 'Icons'))
BACKGROUND_DIR = os.path.join(BASE_DIR, 'Background')
COCKTAILS_DIR = os.path.join(BASE_DIR, 'Cocktails')
COCKTAILS_ICON_DIR = os.path.join(COCKTAILS_DIR, '64_96')


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
from kivy.uix.spinner import Spinner
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.image import Image
from kivy.properties import NumericProperty
from kivy.clock import Clock


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

    def send_gcode(self, gcode: str):
        """Send G-code to printer via Moonraker API with error handling."""
        url = f"{self.base_url}/printer/gcode/script"
        try:
            resp = requests.post(
                url,
                json={"script": gcode},
                timeout=self.timeout
            )
            if resp.status_code not in [200, 204]:
                logging.error(f'Moonraker error {resp.status_code}: {resp.text}')
                return False
            logging.info(f'G-code sent: {gcode}')
            return True
        except requests.exceptions.Timeout:
            logging.error(f'Timeout sending G-code to {url}')
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
        self.positions = self.load_positions()
        self.selected_circle = None

        self.layout = BoxLayout(orientation='vertical', padding=5, spacing=5)

        # Oberer Bereich: Kreise links, Home-Buttons oben rechts
        top_area = BoxLayout(orientation='horizontal', size_hint=(1, 0.6), spacing=6, padding=[5, 5, 5, 5])

        self.slot_area = GridLayout(cols=5, spacing=[10, 10], size_hint=(1, 1), padding=5)
        self.draw_circles()
        top_area.add_widget(self.slot_area)

        home_column = BoxLayout(orientation='vertical', size_hint=(None, 1), width=142, spacing=6)

        home_x_btn = Button(text="X", size_hint=(None, None), size=(64, 64), font_size=18)
        home_y_btn = Button(text="Y", size_hint=(None, None), size=(64, 64), font_size=18)
        home_z_btn = Button(text="Z", size_hint=(None, None), size=(64, 64), font_size=18)
        home_all_btn = Button(text="", size_hint=(None, None), size=(64, 64))

        home_all_icon = Image(source=icon('haus.40.png'), size_hint=(None, None), size=(40, 40))

        def update_home_icon(*_args):
            home_all_icon.center = home_all_btn.center

        home_all_btn.bind(pos=update_home_icon, size=update_home_icon)
        home_all_btn.add_widget(home_all_icon)
        update_home_icon()

        home_x_btn.bind(on_press=partial(self.home_axis, axis='X'))
        home_y_btn.bind(on_press=partial(self.home_axis, axis='Y'))
        home_z_btn.bind(on_press=partial(self.home_axis, axis='Z'))
        home_all_btn.bind(on_press=self.home_all_axes)

        motor_off_btn = Button(text="", size_hint=(None, None), size=(64, 64))
        motor_off_icon = Image(source=icon('aus.40.png'), size_hint=(None, None), size=(40, 40))

        def update_motor_off_icon(*_args):
            motor_off_icon.center = motor_off_btn.center

        motor_off_btn.bind(pos=update_motor_off_icon, size=update_motor_off_icon)
        motor_off_btn.add_widget(motor_off_icon)
        update_motor_off_icon()
        motor_off_btn.bind(on_press=self.disable_motors)

        home_column.add_widget(home_x_btn)
        home_column.add_widget(home_y_btn)
        home_column.add_widget(home_z_btn)

        bottom_home_row = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(134, 64), spacing=6)
        bottom_home_row.add_widget(home_all_btn)
        bottom_home_row.add_widget(motor_off_btn)
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

        self.add_widget(self.layout)

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

        pos = self.positions.get(str(instance.index), {"x": "", "y": ""})
        self.x_input.text = str(pos["x"])
        self.y_input.text = str(pos["y"])
        logging.info(f"Slot {instance.index} ausgewählt")

    def save_position(self, instance):
        if not self.selected_circle:
            logging.warning("Kein Slot ausgewählt.")
            return

        x_text = self.x_input.text.strip()
        y_text = self.y_input.text.strip()
        if not x_text or not y_text:
            logging.warning("Ungültige Koordinaten.")
            return

        try:
            x = float(x_text)
            y = float(y_text)
        except ValueError:
            logging.warning("Ungültige Koordinaten.")
            return

        self.positions[str(self.selected_circle.index)] = {
            "x": x,
            "y": y
        }
        self.store_positions()
        logging.info(f"Slot {self.selected_circle.index} → X={x}, Y={y}")

    def send_position(self, instance):
        """Send G-code move command to stored coordinates."""
        if self.selected_circle:
            pos = self.positions.get(str(self.selected_circle.index))
            if pos:
                command = f"G1 X{pos['x']} Y{pos['y']}"
                moonraker.send_gcode(command)
            else:
                logging.warning(f"No position saved for slot {self.selected_circle.index}")

    def home_axis(self, instance, axis):
        """Home a single axis via Moonraker."""
        command = f"G28 {axis}"
        if moonraker.send_gcode(command):
            logging.info(f"Axis {axis} homed")

    def home_all_axes(self, instance):
        """Home all axes via Moonraker."""
        if moonraker.send_gcode("G28"):
            logging.info("All axes homed")

    def disable_motors(self, instance):
        """Disable stepper motors (holding current off)."""
        if moonraker.send_gcode("M18"):
            logging.info("Motors disabled (holding current off)")

    def load_positions(self):
        """Load positions from JSON with error handling."""
        if os.path.exists("positions.json"):
            try:
                with open("positions.json", "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                logging.error("positions.json is corrupted")
        return {}

    def store_positions(self):
        """Store positions to JSON with error handling."""
        try:
            with open("positions.json", "w") as f:
                json.dump(self.positions, f, indent=4)
            logging.info("Positions saved")
        except IOError as e:
            logging.error(f"Error saving positions: {e}")

class PumpScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = FloatLayout()
        self.add_widget(self.layout)



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
            cols=5,
            spacing=[14, 14],
            padding=[8, 6, 8, 6],
            size_hint_y=None
        )
        self.grid.bind(minimum_height=self.grid.setter('height'))

        scroll = ScrollView(size_hint=(1, 1))
        scroll.add_widget(self.grid)
        root.add_widget(scroll)

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
            self.status_label.text = "Keine Cocktail-Icons in Cocktails/64_96 gefunden."
            return

        for icon_file in icon_files:
            card = BoxLayout(
                orientation='vertical',
                size_hint=(None, None),
                size=(150, 142),
                spacing=6,
                padding=[4, 4, 4, 4]
            )

            icon_path = os.path.join(COCKTAILS_ICON_DIR, icon_file)
            drink_image = Image(
                source=icon_path,
                size_hint=(None, None),
                size=(96, 96),
                pos_hint={'center_x': 0.5}
            )

            name_label = Label(
                text=pretty_cocktail_name(icon_file),
                size_hint_y=None,
                height=32,
                font_size=16,
                color=[1, 1, 1, 1],
                halign='center',
                valign='middle'
            )
            name_label.bind(size=lambda instance, value: setattr(instance, 'text_size', value))
            if self.ui_font:
                name_label.font_name = self.ui_font

            card.add_widget(drink_image)
            card.add_widget(name_label)
            self.grid.add_widget(card)

        self.status_label.text = f"{len(icon_files)} Cocktails geladen"

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

        # Pump-Screen Button
        pump_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal=icon('pump.64.png'),
            background_down=icon('pump.64.png'),
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("pump")
        )
        pump_lbl = Label(text="Pump", size_hint_y=None, height=30)
        pump_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        pump_box.add_widget(pump_btn)
        pump_box.add_widget(pump_lbl)
        self.sidebar.add_widget(pump_box)

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
        self.screen_manager.add_widget(CocktailInputScreen(name="cocktail"))
        self.screen_manager.add_widget(PreparationScreen(name="prep"))
        self.screen_manager.add_widget(MotorPositionScreen(name="motor"))
        self.screen_manager.add_widget(PumpScreen(name="pump"))
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