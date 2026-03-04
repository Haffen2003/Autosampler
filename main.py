import logging
import json
import os
import traceback
from functools import partial

# serial communication replaced by Moonraker HTTP API
import requests
from kivy.config import Config
Config.set('graphics', 'fullscreen', 'auto')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

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

# base directories for resources
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(BASE_DIR, CONFIG.get('icon_dir', 'Icons'))

def icon(name):
    """Return full path to an icon file located in the Icons folder with validation."""
    path = os.path.join(ICON_DIR, name)
    if not os.path.exists(path):
        logging.warning(f'Icon not found: {path}')
        return ""
    return path

from kivy.core.window import Window
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView

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
        content_height = Window.height * 0.65
        scroll_height = content_height - 50

        self.content_area = BoxLayout(orientation='vertical', size_hint=(1, None), height=content_height, pos_hint={'top': 1})
        self.spinner = Spinner(
            text="Cocktail auswählen",
            values=list(self.cocktail_data.keys()),
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
        circle_width = min(Window.width * 0.8, 700)
        self.slot_area = GridLayout(cols=5, spacing=[20, 20], size_hint=(None, None), size=(circle_width, circle_width * 0.6))
        self.slot_area.pos_hint = {'center_x': 0.5, 'y': 0.02}
        self.draw_circles()
        self.layout.add_widget(self.slot_area)

        self.add_widget(self.layout)

    def show_ingredients(self, spinner, text):
        """Load ingredients with race condition protection."""
        if self._loading_ingredients:
            logging.warning('Already loading ingredients, skipping')
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
            for i in ingredients:
                row = BoxLayout(size_hint_y=None, height=50, spacing=10, padding=[5, 5, 5, 5])
                row.ingredient_name = i['name']

                bg_box = FloatLayout(size_hint=(None, None), size=(40, 40))
                with bg_box.canvas.before:
                    Color(0.2, 0.2, 0.2, 1)
                    rect = Rectangle(pos=bg_box.pos, size=bg_box.size)
                    bg_box.rect = rect

                bg_box.bind(pos=lambda inst, val: setattr(inst.rect, 'pos', inst.pos))
                bg_box.bind(size=lambda inst, val: setattr(inst.rect, 'size', inst.size))

                activate_btn = Button(
                    size_hint=(None, None),
                    size=(40, 40),
                    pos_hint={'center_x': 0.5, 'center_y': 0.5},
                    background_normal=icon('stift.40.png'),
                    background_down=icon('stift.40.png'),
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

                delete_btn = Button(
                    size_hint=(None, None),
                    size=(40, 40),
                    background_normal=icon('müll.40.png'),
                    background_down=icon('müll.40.png')
                )
                delete_btn.row = row
                delete_btn.bind(on_press=self.remove_row)

                row.add_widget(bg_box)
                row.add_widget(label)
                row.add_widget(delete_btn)
                self.ingredients_area.add_widget(row)
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

        self.layout = FloatLayout()

        # Kreise mittig zentriert
        self.slot_area = GridLayout(cols=5, spacing=[30, 30], size_hint=(None, None), size=(700, 500))
        self.slot_area.pos_hint = {'center_x': 0.5, 'center_y': 0.65}
        self.draw_circles()
        self.layout.add_widget(self.slot_area)

        # Beschriftung über den Eingabefeldern
        label_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=40, padding=[20, 0, 20, 0], spacing=20)
        label_row.pos_hint = {'x': 0, 'y': 0.18}
        label_row.add_widget(Label(text="X-Achse", size_hint=(None, 1), width=200, font_size=18))
        label_row.add_widget(Label(text="Y-Achse", size_hint=(None, 1), width=200, font_size=18))
        label_row.add_widget(Label(text="", size_hint=(1, 1)))
        self.layout.add_widget(label_row)

        # Eingabefelder + Buttons unten links
        input_area = BoxLayout(orientation='horizontal', size_hint=(1, None), height=70, spacing=20, padding=[20, 10, 20, 10])
        input_area.pos_hint = {'x': 0, 'y': 0.08}

        self.x_input = TextInput(hint_text="X position", multiline=False, size_hint=(None, 1), width=200, font_size=18)
        self.y_input = TextInput(hint_text="Y position", multiline=False, size_hint=(None, 1), width=200, font_size=18)

        save_btn = Button(text="Speichern", size_hint=(None, 1), width=150, font_size=18)
        send_btn = Button(text="Senden", size_hint=(None, 1), width=150, font_size=18)
        save_btn.bind(on_press=self.save_position)
        send_btn.bind(on_press=self.send_position)

        input_area.add_widget(self.x_input)
        input_area.add_widget(self.y_input)
        input_area.add_widget(save_btn)
        input_area.add_widget(send_btn)
        self.layout.add_widget(input_area)

        # Steuerung / Toolhead-Menü unten rechts
        self.control_area = MotorControlMenu(size_hint=(None, None), size=(250, 280))
        self.control_area.pos_hint = {'right': 1, 'y': 0.08}
        self.layout.add_widget(self.control_area)

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
        if self.selected_circle:
            try:
                x = float(self.x_input.text)
                y = float(self.y_input.text)
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

class MotorControlMenu(BoxLayout):
    """Toolhead control menu with axis positions and step controls."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 10
        self.spacing = 4

        self.add_widget(Label(text="Toolhead", size_hint=(1, None), height=30, font_size=20))
        self.add_widget(Label(text="Position: absolute", size_hint=(1, None), height=20))

        axes = ['X', 'Y', 'Z']
        self.axis_inputs = {}
        for axis in axes:
            container = BoxLayout(orientation='vertical', size_hint=(1, None), height=90, spacing=2)

            row1 = BoxLayout(orientation='horizontal', size_hint=(1, None), height=30)
            row1.add_widget(Label(text=axis, size_hint=(None, 1), width=20))
            inp = TextInput(text="", multiline=False, size_hint=(1, 1), font_size=16)
            self.axis_inputs[axis] = inp
            row1.add_widget(inp)
            container.add_widget(row1)

            btn_row = BoxLayout(orientation='horizontal', size_hint=(1, None), height=30, spacing=2)
            for delta in [-100, -10, -1, 1, 10, 100]:
                btn = Button(text=str(delta), size_hint=(None, None), size=(40, 30), font_size=14)
                btn.axis = axis
                btn.delta = delta
                btn.bind(on_press=self.on_increment)
                btn_row.add_widget(btn)
            container.add_widget(btn_row)

            self.add_widget(container)

    def on_increment(self, instance):
        axis = instance.axis
        delta = instance.delta
        inp = self.axis_inputs.get(axis)
        try:
            current = float(inp.text) if inp.text else 0.0
        except ValueError:
            current = 0.0
        new_val = current + delta
        inp.text = str(new_val)
        
        # Send relative G-code
        moonraker.send_gcode("G91")
        moonraker.send_gcode(f"G0 {axis}{delta}")
        moonraker.send_gcode("G90")

class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.layout = FloatLayout()
        self.add_widget(self.layout)

class EinstellungScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.add_widget(MotorControlMenu())

class MainScreen(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'horizontal'
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

        # Screens hinzufügen
        self.screen_manager.add_widget(CocktailInputScreen(name="cocktail"))
        self.screen_manager.add_widget(PreparationScreen(name="prep"))
        self.screen_manager.add_widget(MotorPositionScreen(name="motor"))
        self.screen_manager.add_widget(PumpScreen(name="pump"))
        self.screen_manager.add_widget(HomeScreen(name="home"))

        self.screen_manager.current = "home"
        self.sidebar_container.add_widget(self.sidebar)
        self.add_widget(self.sidebar_container)

        self.add_widget(self.screen_manager)

    def switch_screen(self, name):
        self.screen_manager.current = name

class CocktailApp(App):
    def build(self):
        return MainScreen()

if __name__ == "__main__":
    CocktailApp().run()