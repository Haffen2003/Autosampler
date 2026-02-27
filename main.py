import json
import os
import serial
import time
import traceback
from kivy.config import Config
Config.set('graphics', 'fullscreen', 'auto')


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
from functools import partial
from kivy.graphics import Color, Rectangle









DATA_FILE = "cocktails.json"

def save_cocktails(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def load_cocktails():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
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
        prep_screen = self.manager.get_screen("prep")  # Name im ScreenManager
        prep_screen.cocktail_data = self.cocktail_data
        prep_screen.spinner.values = list(self.cocktail_data.keys())
        self.status_label.text += " → Zubereitung aktualisiert."





class SerialManager:
    _instance = None

    def __init__(self, port='COM5', baudrate=115200):
        try:
            self.ser = serial.Serial(port, baudrate, timeout=2)
            time.sleep(2)
            print(f"[INFO] Serielle Verbindung geöffnet: {port}")
        except Exception as e:
            print(f"[ERROR] Serielle Verbindung fehlgeschlagen: {e}")
            self.ser = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = SerialManager()
        return cls._instance

    def send(self, command):
        if self.ser and self.ser.is_open:
            try:
                self.ser.write((command + '\n').encode('utf-8'))
                print(f"[SEND] → {command}")
                response = self.ser.readline().decode('utf-8').strip()
                print(f"[RECV] ← {response}")
                return response
            except Exception as e:
                print(f"[ERROR] Senden fehlgeschlagen: {e}")
        else:
            print("[WARN] Serielle Verbindung nicht verfügbar.")



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
        self.active_color = None
        self.active_ingredient_name = None
        self.cocktail_data = load_cocktails()

        # Bereits vorhandene Zutaten extrahieren
        existing_names = set()
        for row in self.ingredients_area.children:
            if hasattr(row, 'ingredient_name'):
                existing_names.add(row.ingredient_name)

        # Neue Zutaten hinzufügen
        ingredients = self.cocktail_data.get(text, [])
        for i in ingredients:
            if i['name'] in existing_names:
                continue

            row = BoxLayout(size_hint_y=None, height=50, spacing=10, padding=[5, 5, 5, 5])
            row.ingredient_name = i['name']  # Zutatennamen speichern

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
                background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/stift.40.png',
                background_down='C:/Users/jonas/Desktop/MotorApp/Icons/stift.40.png',
                background_color=(1, 1, 1, 1)  # Immer sichtbar
            )
            activate_btn.bind(on_press=partial(self.set_active_color, name=i['name'], color=i.get('color', [1, 0, 0, 1])))
            row.activate_btn = activate_btn  # Referenz speichern
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
                background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/müll.40.png',
                background_down='C:/Users/jonas/Desktop/MotorApp/Icons/müll.40.png'
            )
            delete_btn.row = row  # Verknüpfe Button mit Zeile
            delete_btn.bind(on_press=self.remove_row)

            row.add_widget(bg_box)
            row.add_widget(label)
            row.add_widget(delete_btn)
            self.ingredients_area.add_widget(row)

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
                print("[WARN] Diese Zutat wurde bereits zugewiesen.")
                return

        instance.assign_ingredient(self.active_ingredient_name, self.active_color)
        print(f"[INFO] Zutat '{self.active_ingredient_name}' zu Slot {instance.index} zugewiesen.")
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
        label_row.add_widget(Label(text="", size_hint=(1, 1)))  # Platzhalter
        self.layout.add_widget(label_row)

        # Eingabefelder + Buttons unten links
        input_area = BoxLayout(orientation='horizontal', size_hint=(1, None), height=70, spacing=20, padding=[20, 10, 20, 10])
        input_area.pos_hint = {'x': 0, 'y': 0.08}

        self.x_input = TextInput(hint_text="X Steps", multiline=False, size_hint=(None, 1), width=200, font_size=18)
        self.y_input = TextInput(hint_text="Y Steps", multiline=False, size_hint=(None, 1), width=200, font_size=18)

        save_btn = Button(text="Speichern", size_hint=(None, 1), width=150, font_size=18)
        send_btn = Button(text="Senden", size_hint=(None, 1), width=150, font_size=18)
        save_btn.bind(on_press=self.save_position)
        send_btn.bind(on_press=self.send_position)

        input_area.add_widget(self.x_input)
        input_area.add_widget(self.y_input)
        input_area.add_widget(save_btn)
        input_area.add_widget(send_btn)
        self.layout.add_widget(input_area)

        # Steuerung + Geschwindigkeit unten rechts
        control_area = BoxLayout(orientation='vertical', size_hint=(None, None), size=(250, 280), spacing=15)
        control_area.pos_hint = {'right': 1, 'y': 0.08}

        self.speed_input = TextInput(hint_text="Geschwindigkeit", multiline=False, size_hint=(1, None), height=50, font_size=18)
        send_speed_btn = Button(text="Speed senden", size_hint=(1, None), height=50, font_size=18)
        send_speed_btn.bind(on_press=self.send_speed)

        btn_forward = Button(text='Vorwärts', size_hint=(1, None), height=50, font_size=18)
        btn_backward = Button(text='Rückwärts', size_hint=(1, None), height=50, font_size=18)
        btn_stop = Button(text='Stopp', size_hint=(1, None), height=50, font_size=18)

        btn_forward.bind(on_press=lambda x: self.send_serial("FORWARD"))
        btn_backward.bind(on_press=lambda x: self.send_serial("BACKWARD"))
        btn_stop.bind(on_press=lambda x: self.send_serial("STOP"))

        control_area.add_widget(self.speed_input)
        control_area.add_widget(send_speed_btn)
        control_area.add_widget(btn_forward)
        control_area.add_widget(btn_backward)
        control_area.add_widget(btn_stop)
        self.layout.add_widget(control_area)

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
        print(f"[INFO] Slot {instance.index} ausgewählt")

    def save_position(self, instance):
        if self.selected_circle:
            self.positions[str(self.selected_circle.index)] = {
                "x": int(self.x_input.text),
                "y": int(self.y_input.text)
            }
            self.store_positions()
            print(f"[SAVE] Slot {self.selected_circle.index} → X={self.x_input.text}, Y={self.y_input.text}")

    def send_position(self, instance):
        if self.selected_circle:
            pos = self.positions.get(str(self.selected_circle.index))
            if pos:
                command = f"MOVE X={pos['x']} Y={pos['y']}"
                self.send_serial(command)

    def send_speed(self, instance):
        speed = self.speed_input.text.strip()
        if speed.isdigit():
            command = f"SPEED={speed}"
            self.send_serial(command)
            print(f"[SEND] Geschwindigkeit gesetzt: {speed}")
        else:
            print("[WARN] Ungültige Eingabe für Geschwindigkeit.")

    def send_serial(self, command):
        SerialManager.get_instance().send(command)

    def load_positions(self):
        if os.path.exists("positions.json"):
            with open("positions.json", "r") as f:
                return json.load(f)
        return {}

    def store_positions(self):
        with open("positions.json", "w") as f:
            json.dump(self.positions, f, indent=4)





class PumpScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Hauptlayout
        self.layout = FloatLayout()
        self.add_widget(self.layout)


class HomeScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Hauptlayout
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
            background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/home.64.png',
            background_down='C:/Users/jonas/Desktop/MotorApp/Icons/home.64.png',
            pos_hint={'center_x': 0.5},
            on_press=lambda x: self.switch_screen("home")
        )
        home_lbl = Label(text="Home", size_hint_y=None, height=30)
        home_box = BoxLayout(orientation='vertical', size_hint_y=None, height=94)
        home_box.add_widget(home_btn)
        home_box.add_widget(home_lbl)
        self.sidebar.add_widget(home_box)


         # Motot-Screen Button
        motor_btn = Button(
            size_hint=(None, None),
            size=(64, 64),
            background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/motor.64.png',
            background_down='C:/Users/jonas/Desktop/MotorApp/Icons/motor.64.png',
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
            background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/pump.64.png',
            background_down='C:/Users/jonas/Desktop/MotorApp/Icons/pump.64.png',
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
            background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/cocktail.64.png',
            background_down='C:/Users/jonas/Desktop/MotorApp/Icons/cocktail.64.png',
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
            background_normal='C:/Users/jonas/Desktop/MotorApp/Icons/shaker.64.png',
            background_down='C:/Users/jonas/Desktop/MotorApp/Icons/shaker.64.png',
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
