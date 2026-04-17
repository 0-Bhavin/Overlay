from pywinauto import Application

app = Application(backend="uia").connect(path="WINWORD.EXE")
word_window = app.top_window()

word_window.wait("visible", timeout=10)

print("✅ Connected to Word")

# Try multiple ways to find File
try:
    # Option 1: as Button
    file_tab = word_window.child_window(title="File", control_type="Button")

    if not file_tab.exists():
        # Option 2: fuzzy search
        elements = word_window.descendants()

        file_tab = None
        for el in elements:
            name = el.window_text()
            if name and "File" in name:
                print("🔍 Found candidate:", name, el.friendly_class_name())
                file_tab = el
                break

    if file_tab:
        print("✅ Found File tab!")

        rect = file_tab.rectangle()
        print(f"📍 Coordinates: {rect}")

        # Optional click
        # file_tab.click_input()

    else:
        print("❌ File tab not found")

except Exception as e:
    print("❌ Error:", e)