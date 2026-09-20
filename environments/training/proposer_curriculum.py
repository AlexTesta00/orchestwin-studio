"""Engineer-authored source references, grouped by business semantics, not inference.

The formulas, public contracts, and literal oracle examples are intentionally
small and reviewable. Translations are variants of the same semantic group.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape

CURRICULUM_ID = "verified-proposer-web-source-v1"
EXCLUDED_FAMILIES = ("guest-list", "expense-split", "expense-splitting", "sales-tax", "temperature")


@dataclass(frozen=True)
class NumericFamily:
    name: str
    title: tuple[str, str]
    fields: tuple[tuple[str, str], tuple[str, str]]
    modes: tuple[tuple[str, str, str], ...]
    domain: str
    rule: str
    examples: tuple[tuple[float, float, str, float], ...]
    invalid: tuple[float, float, str]
    split: str = "train"


# Each expected number is independently specified, not evaluated from the JS
# expression used to author a reference. These are development oracles, not
# held-out model qualification cases.
NUMERIC = (
    NumericFamily(
        "rectangle",
        ("Rectangle", "Rettangolo"),
        (("Length", "Lunghezza"), ("Width", "Larghezza")),
        (("Area", "Area", "a * b"), ("Perimeter", "Perimetro", "2 * (a + b)")),
        "a > 0 && b > 0",
        "Positive length and width; area=length*width, perimeter=2*(length+width).",
        ((3, 4, "Area", 12), (2.5, 4, "Perimeter", 13)),
        (0, 2, "Area"),
    ),
    NumericFamily(
        "right-triangle",
        ("Right triangle", "Triangolo rettangolo"),
        (("First leg", "Primo cateto"), ("Second leg", "Secondo cateto")),
        (("Area", "Area", "a * b / 2"), ("Hypotenuse", "Ipotenusa", "Math.hypot(a, b)")),
        "a > 0 && b > 0",
        "Positive perpendicular legs; area=a*b/2 and hypotenuse=sqrt(a*a+b*b).",
        ((3, 4, "Hypotenuse", 5), (5, 6, "Area", 15)),
        (-1, 2, "Area"),
    ),
    NumericFamily(
        "circular-sector",
        ("Circular sector", "Settore circolare"),
        (("Radius", "Raggio"), ("Angle in degrees", "Angolo in gradi")),
        (
            ("Area", "Area", "Math.PI * a * a * b / 360"),
            ("Arc length", "Lunghezza arco", "Math.PI * a * b / 180"),
        ),
        "a > 0 && b > 0 && b <= 360",
        "Positive radius and angle in (0,360]; sector area=pi*r^2*angle/360 and arc=pi*r*angle/180.",
        ((2, 180, "Area", 6.283185307179586), (3, 90, "Arc length", 4.71238898038469)),
        (2, 361, "Area"),
    ),
    NumericFamily(
        "cylinder",
        ("Cylinder", "Cilindro"),
        (("Radius", "Raggio"), ("Height", "Altezza")),
        (
            ("Volume", "Volume", "Math.PI * a * a * b"),
            ("Surface", "Superficie", "2 * Math.PI * a * (a + b)"),
        ),
        "a > 0 && b > 0",
        "Positive radius and height; volume=pi*r^2*h and total surface=2*pi*r*(r+h).",
        ((2, 3, "Volume", 37.69911184307752), (1, 2, "Surface", 18.84955592153876)),
        (2, -1, "Volume"),
    ),
    NumericFamily(
        "square-prism",
        ("Square prism", "Prisma quadrato"),
        (("Base side", "Lato base"), ("Height", "Altezza")),
        (("Volume", "Volume", "a * a * b"), ("Surface", "Superficie", "2 * a * a + 4 * a * b")),
        "a > 0 && b > 0",
        "Positive square-base side and height; volume=side^2*height, total surface=2*side^2+4*side*height.",
        ((2, 3, "Volume", 12), (3, 5, "Surface", 78)),
        (0, 2, "Surface"),
    ),
    NumericFamily(
        "linear-proportion",
        ("Direct and inverse ratio", "Proporzione diretta e inversa"),
        (("Constant", "Costante"), ("Input", "Valore")),
        (("Direct", "Diretta", "a * b"), ("Inverse", "Inversa", "a / b")),
        "b !== 0",
        "Finite constant and nonzero input; direct=k*x, inverse=k/x. Negative values are allowed.",
        ((-3, 4, "Direct", -12), (9, 2, "Inverse", 4.5)),
        (3, 0, "Direct"),
    ),
    NumericFamily(
        "binomial-square",
        ("Binomial square", "Quadrato di binomio"),
        (("First term", "Primo termine"), ("Second term", "Secondo termine")),
        (
            ("Sum squared", "Somma al quadrato", "(a + b) ** 2"),
            ("Difference squared", "Differenza al quadrato", "(a - b) ** 2"),
        ),
        "true",
        "Finite terms; return (a+b)^2 or (a-b)^2, with negative and decimal terms allowed.",
        ((2, 3, "Sum squared", 25), (-2, 3, "Difference squared", 25)),
        (1, 2, "Unknown"),
    ),
    NumericFamily(
        "ratio-comparison",
        ("Ratio comparison", "Confronto rapporti"),
        (("Part", "Parte"), ("Whole", "Totale")),
        (("Fraction", "Frazione", "a / b"), ("Percent", "Percentuale", "100 * a / b")),
        "a >= 0 && b > 0 && a <= b",
        "Part must be nonnegative and at most a strictly positive whole; fraction=part/whole, percent=100*part/whole.",
        ((3, 8, "Fraction", 0.375), (2, 5, "Percent", 40)),
        (6, 5, "Percent"),
    ),
    NumericFamily(
        "percentage-change",
        ("Percentage change", "Variazione percentuale"),
        (("Initial", "Iniziale"), ("Final", "Finale")),
        (
            ("Change percent", "Variazione percentuale", "100 * (b - a) / a"),
            ("Difference", "Differenza", "b - a"),
        ),
        "a > 0 && b >= 0",
        "Initial value is strictly positive and final value nonnegative; change percent=100*(final-initial)/initial, difference=final-initial.",
        ((80, 100, "Change percent", 25), (100, 65, "Difference", -35)),
        (0, 10, "Difference"),
    ),
    NumericFamily(
        "simple-interest",
        ("One-year simple interest", "Interesse semplice annuale"),
        (("Principal", "Capitale"), ("Annual percent", "Percentuale annua")),
        (("Interest", "Interesse", "a * b / 100"), ("Total", "Totale", "a * (1 + b / 100)")),
        "a >= 0 && b >= 0 && b <= 100",
        "Nonnegative principal and annual rate in [0,100]; one-year interest=principal*rate/100 and total=principal+interest. This is arithmetic, not financial advice.",
        ((1000, 5, "Interest", 50), (200, 2.5, "Total", 205)),
        (-1, 5, "Total"),
    ),
    NumericFamily(
        "compound-growth",
        ("Compound growth", "Crescita composta"),
        (("Annual percent", "Percentuale annua"), ("Whole years", "Anni interi")),
        (
            ("Multiplier", "Moltiplicatore", "(1 + a / 100) ** b"),
            ("Growth percent", "Crescita percentuale", "100 * ((1 + a / 100) ** b - 1)"),
        ),
        "a > -100 && a <= 100 && Number.isInteger(b) && b >= 0 && b <= 30",
        "Annual change is greater than -100 and at most 100 percent; years are integers in [0,30]; multiplier=(1+rate/100)^years and growth percent=100*(multiplier-1).",
        ((10, 2, "Multiplier", 1.21), (20, 2, "Growth percent", 44)),
        (10, 1.5, "Multiplier"),
    ),
    NumericFamily(
        "discount",
        ("Discount", "Sconto"),
        (("Price", "Prezzo"), ("Discount percent", "Percentuale sconto")),
        (
            ("Final price", "Prezzo finale", "a * (1 - b / 100)"),
            ("Saved", "Risparmio", "a * b / 100"),
        ),
        "a >= 0 && b >= 0 && b <= 100",
        "Price is nonnegative and discount lies in [0,100]; final price=price*(1-discount/100), saving=price*discount/100.",
        ((80, 25, "Final price", 60), (50, 12, "Saved", 6)),
        (20, 101, "Saved"),
    ),
    NumericFamily(
        "length-conversion",
        ("Length conversion", "Conversione lunghezze"),
        (("Length", "Lunghezza"), ("Copies", "Copie")),
        (
            ("Metres to centimetres", "Metri in centimetri", "a * b * 100"),
            ("Centimetres to metres", "Centimetri in metri", "a * b / 100"),
        ),
        "a >= 0 && Number.isInteger(b) && b > 0",
        "Nonnegative length and positive integer copies; convert their total using exactly 100 centimetres per metre.",
        ((1.25, 2, "Metres to centimetres", 250), (75, 4, "Centimetres to metres", 3)),
        (2, 0, "Metres to centimetres"),
    ),
    NumericFamily(
        "mass-conversion",
        ("Mass conversion", "Conversione masse"),
        (("Mass", "Massa"), ("Packages", "Confezioni")),
        (
            ("Kilograms to grams", "Chilogrammi in grammi", "a * b * 1000"),
            ("Grams to kilograms", "Grammi in chilogrammi", "a * b / 1000"),
        ),
        "a >= 0 && Number.isInteger(b) && b > 0",
        "Nonnegative mass per package and positive integer packages; use exactly 1000 grams per kilogram.",
        ((0.75, 4, "Kilograms to grams", 3000), (250, 6, "Grams to kilograms", 1.5)),
        (-1, 2, "Grams to kilograms"),
    ),
    NumericFamily(
        "speed-distance",
        ("Speed and distance", "Velocità e distanza"),
        (("Distance or speed", "Distanza o velocità"), ("Hours", "Ore")),
        (
            ("Speed from distance", "Velocità dalla distanza", "a / b"),
            ("Distance from speed", "Distanza dalla velocità", "a * b"),
        ),
        "a >= 0 && b > 0",
        "Nonnegative first value and positive hours; mode speed divides kilometres by hours, mode distance multiplies km/h by hours.",
        ((150, 2, "Speed from distance", 75), (60, 1.5, "Distance from speed", 90)),
        (10, 0, "Speed from distance"),
    ),
    NumericFamily(
        "duration",
        ("Duration", "Durata"),
        (("Hours", "Ore"), ("Minutes", "Minuti")),
        (
            ("Total minutes", "Minuti totali", "60 * a + b"),
            ("Total seconds", "Secondi totali", "3600 * a + 60 * b"),
        ),
        "Number.isInteger(a) && a >= 0 && Number.isInteger(b) && b >= 0 && b < 60",
        "Hours must be nonnegative integers, minutes integer [0,59]; convert to total minutes or seconds.",
        ((2, 15, "Total minutes", 135), (1, 30, "Total seconds", 5400)),
        (1, 60, "Total minutes"),
    ),
    NumericFamily(
        "electrical-energy",
        ("Electrical energy", "Energia elettrica"),
        (("Power in watts", "Potenza in watt"), ("Hours", "Ore")),
        (("Watt hours", "Wattora", "a * b"), ("Kilowatt hours", "Chilowattora", "a * b / 1000")),
        "a >= 0 && b >= 0",
        "Nonnegative watts and hours; watt hours=watts*hours, kilowatt hours=watt hours/1000.",
        ((250, 4, "Watt hours", 1000), (1500, 2, "Kilowatt hours", 3)),
        (-1, 2, "Watt hours"),
    ),
    NumericFamily(
        "density",
        ("Density", "Densità"),
        (
            ("Mass in grams", "Massa in grammi"),
            ("Volume in cubic centimetres", "Volume in centimetri cubi"),
        ),
        (
            ("Grams per cubic centimetre", "Grammi per centimetro cubo", "a / b"),
            ("Kilograms per cubic metre", "Chilogrammi per metro cubo", "1000 * a / b"),
        ),
        "a >= 0 && b > 0",
        "Nonnegative mass in grams and strictly positive volume in cm3; density in g/cm3=mass/volume and kg/m3=1000*mass/volume.",
        ((27, 10, "Grams per cubic centimetre", 2.7), (10, 20, "Kilograms per cubic metre", 500)),
        (1, 0, "Grams per cubic centimetre"),
    ),
    NumericFamily(
        "fuel-efficiency",
        ("Fuel efficiency", "Consumo carburante"),
        (("Kilometres", "Chilometri"), ("Litres", "Litri")),
        (
            ("Kilometres per litre", "Chilometri al litro", "a / b"),
            ("Litres per hundred kilometres", "Litri per cento chilometri", "100 * b / a"),
        ),
        "a > 0 && b > 0",
        "Both distance and litres are strictly positive; km/l=distance/litres and l/100km=100*litres/distance.",
        ((600, 40, "Kilometres per litre", 15), (250, 20, "Litres per hundred kilometres", 8)),
        (0, 2, "Kilometres per litre"),
    ),
    NumericFamily(
        "running-pace",
        ("Running pace", "Ritmo corsa"),
        (("Minutes", "Minuti"), ("Kilometres", "Chilometri")),
        (
            ("Minutes per kilometre", "Minuti al chilometro", "a / b"),
            ("Kilometres per hour", "Chilometri orari", "60 * b / a"),
        ),
        "a > 0 && b > 0",
        "Minutes and kilometres are strictly positive; minutes/km=time/distance and km/h=60*distance/time.",
        ((25, 5, "Minutes per kilometre", 5), (30, 6, "Kilometres per hour", 12)),
        (0, 1, "Kilometres per hour"),
    ),
    NumericFamily(
        "two-value-means",
        ("Two-value means", "Medie di due valori"),
        (("First value", "Primo valore"), ("Second value", "Secondo valore")),
        (
            ("Arithmetic mean", "Media aritmetica", "(a + b) / 2"),
            ("Geometric mean", "Media geometrica", "Math.sqrt(a * b)"),
        ),
        "a >= 0 && b >= 0",
        "Two nonnegative numbers; arithmetic mean=(a+b)/2 and geometric mean=sqrt(a*b).",
        ((3, 9, "Arithmetic mean", 6), (4, 9, "Geometric mean", 6)),
        (-1, 3, "Arithmetic mean"),
    ),
    NumericFamily(
        "integer-division",
        ("Integer division", "Divisione intera"),
        (("Dividend", "Dividendo"), ("Divisor", "Divisore")),
        (("Quotient", "Quoziente", "Math.floor(a / b)"), ("Remainder", "Resto", "a % b")),
        "Number.isSafeInteger(a) && a >= 0 && Number.isSafeInteger(b) && b > 0",
        "Dividend is a nonnegative safe integer, divisor a positive safe integer; quotient is floor(dividend/divisor) and remainder is dividend modulo divisor.",
        ((17, 5, "Quotient", 3), (29, 6, "Remainder", 5)),
        (2.5, 2, "Quotient"),
    ),
    NumericFamily(
        "powers-roots",
        ("Powers and roots", "Potenze e radici"),
        (("Value", "Valore"), ("Integer degree", "Grado intero")),
        (("Power", "Potenza", "a ** b"), ("Root", "Radice", "a ** (1 / b)")),
        "a >= 0 && Number.isInteger(b) && b >= 1 && b <= 10",
        "Value is nonnegative and degree an integer from 1 to 10; power=value^degree, root=value^(1/degree). Reject nonfinite outputs.",
        ((3, 4, "Power", 81), (81, 4, "Root", 3)),
        (3, 0, "Root"),
    ),
    NumericFamily(
        "angle-complement",
        ("Angles", "Angoli"),
        (("First degrees", "Primi gradi"), ("Second degrees", "Secondi gradi")),
        (
            ("Sum", "Somma", "a + b"),
            ("Supplement of sum", "Supplemento della somma", "180 - a - b"),
        ),
        "a >= 0 && b >= 0 && a + b <= 180",
        "Angles are nonnegative and their sum at most 180 degrees; return sum or its supplement to 180.",
        ((30, 45, "Sum", 75), (40, 50, "Supplement of sum", 90)),
        (100, 100, "Sum"),
    ),
    NumericFamily(
        "trapezoid",
        ("Trapezoid area", "Area trapezio"),
        (("Sum of bases", "Somma basi"), ("Height", "Altezza")),
        (("Area", "Area", "a * b / 2"),),
        "a > 0 && b > 0",
        "Strictly positive sum of parallel bases and height; trapezoid area=sum of bases*height/2.",
        ((12, 4, "Area", 24), (7, 3, "Area", 10.5)),
        (0, 3, "Area"),
        "validation",
    ),
    NumericFamily(
        "sphere-shell",
        ("Sphere shell", "Guscio sferico"),
        (("Outer radius", "Raggio esterno"), ("Inner radius", "Raggio interno")),
        (("Shell volume", "Volume guscio", "4 * Math.PI * (a ** 3 - b ** 3) / 3"),),
        "a > 0 && b >= 0 && b < a",
        "Outer radius must be positive, inner radius nonnegative and smaller; shell volume=4*pi*(outer^3-inner^3)/3.",
        ((2, 1, "Shell volume", 29.321531433504735), (1, 0, "Shell volume", 4.1887902047863905)),
        (2, 2, "Shell volume"),
        "validation",
    ),
    NumericFamily(
        "volume-conversion",
        ("Volume conversion", "Conversione volumi"),
        (("Litres", "Litri"), ("Bottles", "Bottiglie")),
        (("Millilitres", "Millilitri", "a * b * 1000"),),
        "a >= 0 && Number.isInteger(b) && b > 0",
        "Nonnegative litres per bottle and positive integer bottles; total millilitres=litres*bottles*1000.",
        ((0.5, 6, "Millilitres", 3000), (1.25, 2, "Millilitres", 2500)),
        (1, -2, "Millilitres"),
        "validation",
    ),
    NumericFamily(
        "recipe-scaling",
        ("Recipe scaling", "Scala ricetta"),
        (("Grams per serving", "Grammi per porzione"), ("Servings", "Porzioni")),
        (("Total grams", "Grammi totali", "a * b"),),
        "a > 0 && Number.isInteger(b) && b > 0",
        "Positive ingredient grams per serving and positive integer servings; return their product in grams.",
        ((75, 4, "Total grams", 300), (12.5, 3, "Total grams", 37.5)),
        (0, 4, "Total grams"),
        "validation",
    ),
    NumericFamily(
        "break-even",
        ("Break-even units", "Unità di pareggio"),
        (("Fixed cost", "Costo fisso"), ("Margin per unit", "Margine unitario")),
        (("Whole units", "Unità intere", "Math.ceil(a / b)"),),
        "a >= 0 && b > 0",
        "Nonnegative fixed cost and strictly positive margin per unit; minimum whole units=ceiling(fixed cost/margin).",
        ((101, 20, "Whole units", 6), (100, 25, "Whole units", 4)),
        (10, 0, "Whole units"),
        "validation",
    ),
    NumericFamily(
        "fraction-complement",
        ("Fraction complement", "Complemento frazione"),
        (("Numerator", "Numeratore"), ("Denominator", "Denominatore")),
        (("Complement", "Complemento", "(b - a) / b"),),
        "Number.isSafeInteger(a) && a >= 0 && Number.isSafeInteger(b) && b > 0 && a <= b",
        "Safe integer numerator from zero to a positive safe integer denominator; return (denominator-numerator)/denominator.",
        ((1, 4, "Complement", 0.75), (3, 5, "Complement", 0.4)),
        (5, 4, "Complement"),
        "validation",
    ),
)


@dataclass(frozen=True)
class StatefulFamily:
    name: str
    title: tuple[str, str]
    modes: tuple[tuple[str, str], ...]
    rule: str
    body: str
    sequence: tuple
    invalid: tuple
    split: str = "train"


STATEFUL = (
    StatefulFamily(
        "stock-inventory",
        ("Stock inventory", "Magazzino"),
        (("Receive", "Ricevi"), ("Dispatch", "Spedisci")),
        "Positive safe-integer quantities keyed by trimmed item name. Receive increases stock; dispatch rejects missing or insufficient stock. snapshot() returns a copy of the item-to-quantity map.",
        "const next = (store[label] || 0) + (action === 'Receive' ? amount : -amount);\n    if (next < 0) throw new Error('Insufficient stock');\n    store[label] = next;",
        (
            ("Receive", "Pens", 8, {"Pens": 8}),
            ("Dispatch", "Pens", 3, {"Pens": 5}),
            ("Receive", "Paper", 2, {"Pens": 5, "Paper": 2}),
        ),
        ("Dispatch", "Pens", 6),
    ),
    StatefulFamily(
        "loyalty-points",
        ("Loyalty points", "Punti fedeltà"),
        (("Earn", "Guadagna"), ("Redeem", "Riscatta")),
        "Positive safe-integer points per trimmed customer key. Earn adds points; redeem subtracts and rejects insufficient points. snapshot() returns a copied customer-to-points map.",
        "const next = (store[label] || 0) + (action === 'Earn' ? amount : -amount);\n    if (next < 0) throw new Error('Insufficient points');\n    store[label] = next;",
        (
            ("Earn", "Alex", 20, {"Alex": 20}),
            ("Redeem", "Alex", 7, {"Alex": 13}),
            ("Earn", "Sam", 5, {"Alex": 13, "Sam": 5}),
        ),
        ("Redeem", "Alex", 14),
    ),
    StatefulFamily(
        "capacity-booking",
        ("Capacity booking", "Prenotazioni capacità"),
        (("Set capacity", "Imposta capacità"), ("Reserve", "Prenota")),
        "Positive safe-integer quantities per room. Set capacity creates or replaces the remaining capacity; reserve reduces remaining capacity and rejects unavailable seats. snapshot() returns copied remaining capacities.",
        "const next = action === 'Set capacity' ? amount : (store[label] || 0) - amount;\n    if (next < 0) throw new Error('Capacity exceeded');\n    store[label] = next;",
        (
            ("Set capacity", "Room A", 12, {"Room A": 12}),
            ("Reserve", "Room A", 4, {"Room A": 8}),
            ("Set capacity", "Room B", 6, {"Room A": 8, "Room B": 6}),
        ),
        ("Reserve", "Room A", 9),
    ),
    StatefulFamily(
        "shopping-quantities",
        ("Shopping quantities", "Quantità carrello"),
        (("Add", "Aggiungi"), ("Remove", "Rimuovi")),
        "Positive safe-integer item quantities; add increases quantity, remove rejects excess and deletes an item when quantity becomes zero. snapshot() returns a defensive copy.",
        "const next = (store[label] || 0) + (action === 'Add' ? amount : -amount);\n    if (next < 0) throw new Error('Quantity exceeded');\n    if (next === 0) delete store[label]; else store[label] = next;",
        (
            ("Add", "Book", 2, {"Book": 2}),
            ("Add", "Pen", 3, {"Book": 2, "Pen": 3}),
            ("Remove", "Book", 2, {"Pen": 3}),
        ),
        ("Remove", "Pen", 4),
    ),
    StatefulFamily(
        "task-priorities",
        ("Task priorities", "Priorità attività"),
        (("Set priority", "Imposta priorità"), ("Raise priority", "Aumenta priorità")),
        "Positive safe-integer priorities per task name. Set priority creates or replaces a priority; raise priority adds to an existing task and rejects unknown tasks. snapshot() retrieves a copied task-to-priority map.",
        "if (action === 'Raise priority' && !Object.hasOwn(store, label)) throw new Error('Unknown task');\n    const next = action === 'Set priority' ? amount : store[label] + amount;\n    if (!Number.isSafeInteger(next)) throw new Error('Priority overflow');\n    store[label] = next;",
        (
            ("Set priority", "Write", 2, {"Write": 2}),
            ("Raise priority", "Write", 3, {"Write": 5}),
            ("Set priority", "Read", 1, {"Write": 5, "Read": 1}),
        ),
        ("Raise priority", "Missing", 1),
    ),
    StatefulFamily(
        "named-counters",
        ("Named counters", "Contatori nominati"),
        (("Increment", "Incrementa"), ("Reset to", "Reimposta a")),
        "Positive safe-integer amounts. Increment adds to an independent named counter, Reset to replaces it. Reject unsafe accumulated values before modifying state. snapshot() returns a copy.",
        "const next = action === 'Increment' ? (store[label] || 0) + amount : amount;\n    if (!Number.isSafeInteger(next)) throw new Error('Counter overflow');\n    store[label] = next;",
        (
            ("Increment", "Visits", 3, {"Visits": 3}),
            ("Increment", "Visits", 4, {"Visits": 7}),
            ("Reset to", "Visits", 2, {"Visits": 2}),
        ),
        ("Increment", "Visits", 9007199254740991),
    ),
    StatefulFamily(
        "reading-progress",
        ("Reading progress", "Progresso lettura"),
        (("Set total", "Imposta totale"), ("Read pages", "Leggi pagine")),
        "Positive safe-integer pages keyed by book. Set total initializes remaining pages; Read pages subtracts and rejects more than remaining pages. snapshot() returns copied remaining pages.",
        "const next = action === 'Set total' ? amount : (store[label] || 0) - amount;\n    if (next < 0) throw new Error('Too many pages');\n    store[label] = next;",
        (
            ("Set total", "Novel", 90, {"Novel": 90}),
            ("Read pages", "Novel", 30, {"Novel": 60}),
            ("Read pages", "Novel", 20, {"Novel": 40}),
        ),
        ("Read pages", "Novel", 41),
        "validation",
    ),
    StatefulFamily(
        "team-votes",
        ("Team votes", "Voti squadra"),
        (("Vote", "Vota"), ("Withdraw", "Ritira")),
        "Positive safe-integer vote counts per option. Vote adds, withdraw subtracts and rejects unavailable votes; options at zero remain retrievable. snapshot() returns copied totals.",
        "const next = (store[label] || 0) + (action === 'Vote' ? amount : -amount);\n    if (next < 0) throw new Error('Votes exceeded');\n    store[label] = next;",
        (
            ("Vote", "Blue", 5, {"Blue": 5}),
            ("Vote", "Red", 3, {"Blue": 5, "Red": 3}),
            ("Withdraw", "Blue", 2, {"Blue": 3, "Red": 3}),
        ),
        ("Withdraw", "Red", 4),
        "validation",
    ),
)


def js(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


PARSE_NUMBER = """function readNumber(raw) {
  if (typeof raw !== 'string' || !/^[+-]?(?:\\d+(?:[.,]\\d*)?|[.,]\\d+)$/.test(raw.trim())) {
    throw new Error('Enter a valid decimal number');
  }
  const value = Number(raw.trim().replace(',', '.'));
  if (!Number.isFinite(value)) throw new Error('Number is outside the finite range');
  return value;
}
"""


def prototype(family, locale):
    language = 0 if locale == "en" else 1
    stateful = isinstance(family, StatefulFamily)
    fields = (("Name", "Nome"), ("Amount", "Quantità")) if stateful else family.fields
    elements = [
        dict(
            id=f"field-{index}",
            code=f"ELM-{index:03}",
            kind="TEXT_INPUT",
            field_name=name,
            content=label[language],
            required=True,
        )
        for index, (name, label) in enumerate(zip(("first", "second"), fields, strict=True), 1)
    ]
    elements += [
        dict(
            id="mode",
            code="ELM-003",
            kind="SELECT",
            field_name="mode",
            required=True,
            content=("Operation", "Operazione")[language],
            options=[mode[language] for mode in family.modes],
        ),
        dict(id="apply", code="ELM-004", kind="BUTTON", content=("Apply", "Applica")[language]),
    ]
    return dict(
        screens=[
            dict(id="entry", code="SCR-001", title=family.title[language], elements=elements),
            dict(
                id="result",
                code="SCR-002",
                title=("Result", "Risultato")[language],
                elements=[
                    dict(
                        id="output",
                        code="ELM-005",
                        kind="TEXT",
                        content=("Dynamic result", "Risultato dinamico")[language],
                    ),
                    dict(
                        id="back",
                        code="ELM-006",
                        kind="LINK",
                        content=("Back", "Indietro")[language],
                    ),
                ],
            ),
        ],
        transitions=[
            dict(trigger_element_id="apply", source_screen_id="entry", target_screen_id="result"),
            dict(trigger_element_id="back", source_screen_id="result", target_screen_id="entry"),
        ],
    )


def core_source(family):
    if isinstance(family, NumericFamily):
        cases = "\n".join(
            f"    case {js(mode[0])}: result = {mode[2]}; break;" for mode in family.modes
        )
        return (
            PARSE_NUMBER
            + f"""function compute(a, b, mode) {{
  if (typeof a !== 'number' || typeof b !== 'number' || !Number.isFinite(a) || !Number.isFinite(b)) throw new Error('Finite numbers required');
  if (!({family.domain})) throw new Error('Inputs outside allowed domain');
  let result;
  switch (mode) {{
{cases}
    default: throw new Error('Choose a valid operation');
  }}
  if (!Number.isFinite(result)) throw new Error('Result is outside the finite range');
  return result;
}}
if (typeof module !== 'undefined') module.exports = {{ readNumber, compute }};
"""
        )
    return (
        PARSE_NUMBER
        + f"""function createService() {{
  const store = Object.create(null);
  function snapshot() {{ return {{ ...store }}; }}
  function apply(action, name, amount) {{
    if (!{js([mode[0] for mode in family.modes])}.includes(action)) throw new Error('Choose a valid operation');
    if (typeof name !== 'string' || !name.trim()) throw new Error('Name is required');
    if (!Number.isSafeInteger(amount) || amount <= 0) throw new Error('Positive integer required');
    const label = name.trim();
    {family.body}
    return snapshot();
  }}
  return {{ apply, snapshot }};
}}
if (typeof module !== 'undefined') module.exports = {{ readNumber, createService }};
"""
    )


def source_bundle(family, locale):
    proto = prototype(family, locale)
    stateful = isinstance(family, StatefulFamily)
    core = core_source(family)
    binding = "  const service = createService();\n" if stateful else ""
    invocation = (
        "service.apply(mode.value, first.value, readNumber(second.value))"
        if stateful
        else "compute(readNumber(first.value), readNumber(second.value), mode.value)"
    )
    app = (
        core
        + f"""if (typeof document !== 'undefined') {{
{binding}  const form = document.getElementById('form');
  const first = document.getElementById('first');
  const second = document.getElementById('second');
  const mode = document.getElementById('mode');
  const entry = document.getElementById('entry');
  const result = document.getElementById('result');
  const output = document.getElementById('output');
  const error = document.getElementById('error');
  form.addEventListener('submit', event => {{
    event.preventDefault();
    error.textContent = '';
    try {{
      const value = {invocation};
      output.textContent = {"JSON.stringify(value)" if stateful else "String(Number(value.toPrecision(12)))"};
      entry.hidden = true; result.hidden = false; output.focus();
    }} catch (failure) {{ error.textContent = failure.message; }}
  }});
  document.getElementById('back').addEventListener('click', event => {{
    event.preventDefault(); result.hidden = true; entry.hidden = false; first.focus();
  }});
}}
"""
    )
    page = html_source(proto, family, locale)
    tests = tests_source(family)
    return {"app.js": app, "app.test.cjs": tests, "index.html": page}, proto


def html_source(proto, family, locale):
    fields = proto["screens"][0]["elements"]
    labels = "\n".join(
        f'<label for="{element["field_name"]}">{escape(element["content"])}</label><input id="{element["field_name"]}" name="{element["field_name"]}" data-design-element="{element["code"]}" required>'
        for element in fields[:2]
    )
    options = "".join(
        f'<option value="{escape(mode[0], quote=True)}">{escape(mode[0 if locale == "en" else 1])}</option>'
        for mode in family.modes
    )
    return f"""<!doctype html>
<html lang="{locale}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(proto["screens"][0]["title"])}</title>
<style>body{{font:18px system-ui;margin:0;padding:24px;background:#f4f5f8;color:#182237}}main{{max-width:480px;margin:auto;background:white;padding:24px;border-radius:16px}}label{{display:block;margin-top:16px}}input,select,button{{box-sizing:border-box;width:100%;padding:12px;font:inherit;margin-top:6px}}button{{background:#404fcd;color:white;border:0;border-radius:8px;margin-top:24px}}[hidden]{{display:none}}#error{{color:#a51a31}}output{{display:block;overflow-wrap:anywhere;margin:24px 0}}</style></head>
<body><main><section id="entry" data-design-screen="SCR-001"><h1>{escape(proto["screens"][0]["title"])}</h1>
<form id="form" novalidate>{labels}
<label for="mode">{escape(fields[2]["content"])}</label><select id="mode" name="mode" data-design-element="ELM-003" required><option value="" disabled selected>—</option>{options}</select>
<p id="error" role="alert"></p><button data-design-element="ELM-004" data-design-target="SCR-002" type="submit">{escape(fields[3]["content"])}</button></form></section>
<section id="result" data-design-screen="SCR-002" hidden><h1>{escape(proto["screens"][1]["title"])}</h1><output id="output" data-design-element="ELM-005" tabindex="-1" aria-live="polite"></output>
<a id="back" href="#entry" data-design-element="ELM-006" data-design-target="SCR-001">{escape(proto["screens"][1]["elements"][1]["content"])}</a></section></main><script src="app.js"></script></body></html>
"""


def tests_source(family):
    imports = (
        "readNumber, createService" if isinstance(family, StatefulFamily) else "readNumber, compute"
    )
    text = f"const test = require('node:test');\nconst assert = require('node:assert/strict');\nconst {{ {imports} }} = require('./app.js');\n"
    text += """test('decimal input conversion rejects empty and nonnumeric text', () => {
  assert.equal(readNumber(' 1,25 '), 1.25);
  assert.equal(readNumber('-0.5'), -0.5);
  for (const value of ['', ' ', 'Infinity', '0xff', '1x']) assert.throws(() => readNumber(value));
});
"""
    if isinstance(family, NumericFamily):
        text += "test('business outputs and rejected domain', () => {\n"
        for a, b, mode, expected in family.examples:
            text += f"  assert.ok(Math.abs(compute({js(a)}, {js(b)}, {js(mode)}) - {js(expected)}) < 1e-9);\n"
        text += f"  assert.throws(() => compute(...{js(family.invalid)}));\n"
        text += "  assert.throws(() => compute('3', 2, 'Unknown'));\n});\n"
    else:
        text += "test('retained records, retrieval, failure atomicity and isolated instances', () => {\n  const service = createService();\n"
        for mode, key, amount, expected in family.sequence:
            text += f"  assert.deepEqual(service.apply({js(mode)}, {js(key)}, {amount}), {js(expected)});\n"
        text += f"  const before = service.snapshot();\n  assert.throws(() => service.apply(...{js(family.invalid)}));\n"
        text += "  assert.deepEqual(service.snapshot(), before);\n  const copy = service.snapshot(); copy.changed = 99;\n  assert.deepEqual(service.snapshot(), before);\n  assert.deepEqual(createService().snapshot(), {});\n});\n"
    return text


def all_families():
    families = NUMERIC + STATEFUL
    assert len({family.name for family in families}) == len(families)
    assert not set(EXCLUDED_FAMILIES) & {family.name for family in families}
    return families
