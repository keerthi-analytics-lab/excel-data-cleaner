"""Generate the synthetic, intentionally messy sample datasets.

The data is fake by design:
  * names are random combinations of common first/last names,
  * emails use the reserved ``example.com`` domain,
  * phone numbers use the 555-0100..555-0199 range reserved for fiction.

A fixed random seed makes the output reproducible. Run from the project root:

    python scripts/generate_sample_data.py
"""

from __future__ import annotations

import csv
import random
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook

SEED = 42
SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"

FIRST_NAMES = [
    "Olivia", "Liam", "Emma", "Noah", "Ava", "Mateo", "Sophia", "Ethan", "Isabella",
    "Lucas", "Mia", "Mason", "Amelia", "Logan", "Harper", "Elijah", "Evelyn", "James",
    "Abigail", "Benjamin", "Emily", "Henry", "Chloé", "José", "Zoë", "Priya", "Arjun",
    "Wei", "Fatima", "Omar", "Hannah", "Grace", "Daniel", "Aisha", "Lena", "Diego",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Wilson", "Anderson", "Taylor", "Thomas", "Moore", "Martin",
    "Lee", "Thompson", "White", "O'Neil", "Nguyen", "Patel", "Kim", "Clark", "Lewis",
    "Walker", "Hall", "Young", "King", "Wright", "Müller", "Silva",
]
# (city, country, area code)
LOCATIONS = [
    ("New York", "United States", "212"), ("Chicago", "United States", "312"),
    ("Austin", "United States", "512"), ("Seattle", "United States", "206"),
    ("Denver", "United States", "303"), ("Boston", "United States", "617"),
    ("Phoenix", "United States", "602"), ("Portland", "United States", "503"),
    ("Toronto", "Canada", "416"), ("Vancouver", "Canada", "604"),
    ("Montreal", "Canada", "514"), ("Calgary", "Canada", "403"), ("Ottawa", "Canada", "613"),
]
COUNTRY_VARIANTS = {
    "United States": ["United States", "USA", "usa", "US", "U.S.A.", "united states"],
    "Canada": ["Canada", "CA", "canada", "CAN", "CANADA"],
}
MEMBERSHIP = ["Bronze", "Silver", "Gold"]
MISSING_MARKERS = ["", "", "N/A", "null", "-"]

CUSTOMER_HEADERS = [
    " Customer ID", "Full Name", "Email Address", "Phone No.", "City ", "Country",
    "SignupDate", "Total Spent ($)", "Membership",
]


@dataclass
class Customer:
    customer_id: str
    first: str
    last: str
    email: str
    phone: str  # 10 digits
    city: str
    country: str
    signup: date
    spent: float
    membership: str


def ascii_slug(text: str) -> str:
    """'Zoë O'Neil' -> 'zoeoneil' (for fake email addresses)."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in plain.lower() if ch.isalnum())


def make_customers(rng: random.Random, count: int) -> list[Customer]:
    customers = []
    start = date(2022, 1, 1)
    for number in range(1, count + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        city, country, area = rng.choice(LOCATIONS)
        customers.append(
            Customer(
                customer_id=f"C-{number:04d}",
                first=first,
                last=last,
                email=f"{ascii_slug(first)}.{ascii_slug(last)}{number}@example.com",
                phone=f"{area}5550{rng.randint(100, 199)}"[:10],
                city=city,
                country=country,
                signup=start + timedelta(days=rng.randint(0, 1460)),
                spent=round(rng.uniform(0, 5000), 2),
                membership=rng.choice(MEMBERSHIP),
            )
        )
    return customers


def messy_case(rng: random.Random, text: str) -> str:
    return rng.choice([text, text, text.lower(), text.upper()])


def messy_spaces(rng: random.Random, text: str) -> str:
    if rng.random() < 0.15:
        return f"  {text.replace(' ', '   ')} "
    return text


def messy_phone(rng: random.Random, digits: str) -> str:
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return rng.choice(
        [f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}", f"+1 {a} {b} {c}", f"1-{a}-{b}-{c}", digits]
    )


def messy_date(rng: random.Random, value: date) -> str:
    return value.strftime(rng.choice(["%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%d %b %Y", "%m-%d-%Y"]))


def messy_amount(rng: random.Random, value: float) -> str:
    return rng.choice(
        [f"{value:.2f}", f"${value:,.2f}", f"USD {value:.2f}", f" {value:,.1f} ", f"{value:g}"]
    )


def render_customer(rng: random.Random, c: Customer) -> list[str]:
    """Turn a clean record into a messy CSV row."""
    customer_id = c.customer_id.lower() if rng.random() < 0.2 else c.customer_id
    name = messy_spaces(rng, messy_case(rng, f"{c.first} {c.last}"))
    email = c.email.upper() if rng.random() < 0.15 else c.email
    if rng.random() < 0.1:
        email = f" {email}  "
    phone = rng.choice(MISSING_MARKERS) if rng.random() < 0.08 else messy_phone(rng, c.phone)
    city = rng.choice(MISSING_MARKERS) if rng.random() < 0.08 else messy_case(rng, c.city)
    country = rng.choice(COUNTRY_VARIANTS[c.country])
    spent = rng.choice(MISSING_MARKERS) if rng.random() < 0.06 else messy_amount(rng, c.spent)
    membership = (
        rng.choice(MISSING_MARKERS)
        if rng.random() < 0.1
        else messy_spaces(rng, messy_case(rng, c.membership))
    )
    return [
        customer_id, name, email, phone, city, country,
        messy_date(rng, c.signup), spent, membership,
    ]


def build_customer_rows(rng: random.Random) -> list[list[str]]:
    customers = make_customers(rng, 140)
    rows = [render_customer(rng, c) for c in customers]

    # Pick disjoint rows for each kind of problem so every case is visible.
    picks = rng.sample(range(len(rows)), 30)
    invalid_emails = ["{}.example.com", "{}@", "{}@@example.com", "{}@example", "{} @example.com"]
    for idx, template in zip(picks[0:5], invalid_emails):
        rows[idx][2] = template.format(ascii_slug(customers[idx].first))
    for idx, bad_phone in zip(picks[5:8], ["555-0147", "212-555-01478", "call me"]):
        rows[idx][3] = bad_phone
    for idx, bad_date in zip(picks[8:11], ["13/45/2023", "TBD", "2023-02-30"]):
        rows[idx][6] = bad_date
    for idx, bad_amount in zip(picks[11:13], ["abc", "12..5"]):
        rows[idx][7] = bad_amount
    for idx in picks[13:15]:
        rows[idx][7] = f"({rng.uniform(10, 90):.2f})"  # refund shown as negative
    for idx in picks[15:18]:
        rows[idx][2] = rng.choice(["", "N/A"])  # missing required email
    rows[picks[18]][1] = "   "  # missing required name

    # Duplicates: the same customer exported again, often with different formatting.
    duplicates = []
    for idx in picks[19:27]:
        duplicates.append((idx, render_customer(rng, customers[idx])))
    for idx in picks[27:30]:
        duplicates.append((idx, list(rows[idx])))  # exact copies
    for source_idx, row in sorted(duplicates, key=lambda item: item[0], reverse=True):
        insert_at = rng.randint(source_idx + 1, len(rows))
        rows.insert(insert_at, row)

    # Completely empty rows, as left behind by manual edits.
    for _ in range(3):
        rows.insert(rng.randint(1, len(rows)), [""] * len(CUSTOMER_HEADERS))
    rows.insert(rng.randint(1, len(rows)), ["  "] * len(CUSTOMER_HEADERS))
    return rows


def write_customers(rng: random.Random) -> Path:
    path = SAMPLE_DIR / "raw_customer_records.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CUSTOMER_HEADERS)
        writer.writerows(build_customer_rows(rng))
    return path


# --------------------------------------------------------------------------- sales orders

PRODUCTS = {
    "Wireless Mouse": 799.0, "USB-C Cable": 349.0, "Laptop Stand": 1499.0,
    "Mechanical Keyboard": 3299.0, "HD Webcam": 2199.0, "Desk Lamp": 999.0,
    "Notebook Pack": 249.0, "Office Chair": 8999.0,
}
REGION_VARIANTS = {
    "North": ["North", "north", "NORTH ", "N"], "South": ["South", "south", "S"],
    "East": ["East", "EAST", "E"], "West": ["West", " west", "W"],
}
SALES_HEADERS = [
    "Order ID", "Order Date", "Customer Email", "Product", "Quantity", "Unit Price (INR)", "Region",
]


def build_sales_rows(rng: random.Random) -> list[list[object]]:
    rows: list[list[object]] = []
    for number in range(1, 61):
        order_day = datetime(2026, 1, 1) + timedelta(days=rng.randint(0, 89))
        product = rng.choice(list(PRODUCTS))
        price = PRODUCTS[product]
        region = rng.choice(list(REGION_VARIANTS))
        date_cell: object = (
            order_day
            if rng.random() < 0.5
            else order_day.strftime(rng.choice(["%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d.%m.%Y"]))
        )
        price_cell: object = rng.choice(
            [price, price, f"₹{price:,.2f}", f"Rs. {price:,.0f}", f"INR {price:,.2f}"]
        )
        quantity = rng.randint(1, 5)
        rows.append([
            f"ord-{1000 + number}" if rng.random() < 0.2 else f"ORD-{1000 + number}",
            date_cell,
            f"customer{rng.randint(1, 40)}@example.com".upper()
            if rng.random() < 0.1
            else f"customer{rng.randint(1, 40)}@example.com",
            messy_case(rng, product),
            quantity if rng.random() < 0.6 else f" {quantity} ",
            price_cell,
            rng.choice(REGION_VARIANTS[region]) if rng.random() > 0.08 else None,
        ])

    picks = rng.sample(range(len(rows)), 9)
    rows[picks[0]][4] = "three"  # invalid quantity
    rows[picks[1]][4] = None  # missing quantity -> drop_row
    rows[picks[2]][4] = "N/A"
    rows[picks[3]][2] = "customer7@example"  # invalid email
    rows[picks[4]][1] = "31/02/2026"  # impossible date
    for idx in sorted(picks[5:9], reverse=True):  # same order exported twice
        rows.insert(rng.randint(idx + 1, len(rows)), list(rows[idx]))
    return rows


def write_sales(rng: random.Random) -> Path:
    path = SAMPLE_DIR / "raw_sales_orders.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Orders"
    sheet.append(SALES_HEADERS)
    for row in build_sales_rows(rng):
        sheet.append(row)
    for cell in sheet["B"][1:]:
        if isinstance(cell.value, datetime):
            cell.number_format = "dd/mm/yyyy"
    workbook.save(path)
    return path


def main() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    for path in (write_customers(rng), write_sales(rng)):
        print(f"Wrote {path.relative_to(SAMPLE_DIR.parents[1])}")


if __name__ == "__main__":
    main()
