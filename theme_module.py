import ttkbootstrap as ttk

def get_available_themes():
    """Returns a list of available ttkbootstrap themes."""
    # Create a temporary style object to get theme names if needed, 
    # but ttkbootstrap has a built-in list.
    return ttk.Style().theme_names()

def set_theme(root, theme_name):
    """
    Sets the theme for the given root window.
    Args:
        root (ttk.Window): The main application window.
        theme_name (str): The name of the theme to apply.
    """
    style = ttk.Style()
    style.theme_use(theme_name)
    print(f"Theme changed to: {theme_name}")
