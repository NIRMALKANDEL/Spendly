"""Transaction categories, currencies and theme presets shared across the app."""

EXPENSE_CATEGORIES = [
    "Food",
    "Groceries",
    "Rent",
    "Bills",
    "Transport",
    "Shopping",
    "Health",
    "Entertainment",
    "Education",
    "Travel",
    "Other",
]

INCOME_CATEGORIES = [
    "Salary",
    "Freelance",
    "Business",
    "Investment",
    "Gift",
    "Other",
]

CATEGORIES = {"expense": EXPENSE_CATEGORIES, "income": INCOME_CATEGORIES}

KINDS = ("expense", "income")

# code -> (symbol, digit grouping). Indian grouping renders 1,23,45,678.
CURRENCIES = {
    "INR": ("₹", "indian", "Indian Rupee"),
    "NPR": ("रू", "indian", "Nepalese Rupee"),
    "USD": ("$", "western", "US Dollar"),
    "EUR": ("€", "western", "Euro"),
    "GBP": ("£", "western", "British Pound"),
    "AUD": ("A$", "western", "Australian Dollar"),
    "CAD": ("C$", "western", "Canadian Dollar"),
}

THEMES = {
    "forest": {"label": "Forest", "accent": "#1a472a", "accent_2": "#c17f24"},
    "ocean": {"label": "Ocean", "accent": "#1d4e89", "accent_2": "#d0703a"},
    "plum": {"label": "Plum", "accent": "#5b2a6e", "accent_2": "#c9973a"},
    "terracotta": {"label": "Terracotta", "accent": "#9c3d24", "accent_2": "#3f7c6b"},
    "graphite": {"label": "Graphite", "accent": "#2f3640", "accent_2": "#c0563b"},
}

MODES = ("system", "light", "dark")

FREQUENCIES = ("weekly", "monthly", "yearly")
