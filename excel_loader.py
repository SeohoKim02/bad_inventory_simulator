import pandas as pd


REQUIRED_SHEETS = ["stores", "products", "inventory", "routes"]


def load_excel_file(uploaded_file):
    excel_data = pd.ExcelFile(uploaded_file)

    sheet_names = excel_data.sheet_names

    missing_sheets = []
    for sheet in REQUIRED_SHEETS:
        if sheet not in sheet_names:
            missing_sheets.append(sheet)

    if missing_sheets:
        return None, missing_sheets

    stores = pd.read_excel(uploaded_file, sheet_name="stores")
    products = pd.read_excel(uploaded_file, sheet_name="products")
    inventory = pd.read_excel(uploaded_file, sheet_name="inventory")
    routes = pd.read_excel(uploaded_file, sheet_name="routes")

    data = {
        "stores": stores,
        "products": products,
        "inventory": inventory,
        "routes": routes,
    }

    return data, []
