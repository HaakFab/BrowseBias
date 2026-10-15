"""
Bias Engine — Earth Epochs Sequence
====================================
Chronological sequence of Earth Geological Periods, Epochs, and Stages
used for automated cohort versioning and dataset archiving.
"""
from typing import List, Optional

# Curated chronological sequence of Geological Periods and Epochs
EARTH_EPOCHS: List[str] = [
    # Precambrian
    "Cryogenian",
    "Ediacaran",
    # Cambrian
    "Cambrian",
    "Terreneuvian",
    "Furongian",
    # Ordovician
    "Ordovician",
    "Tremadocian",
    "Darriwilian",
    "Hirnantian",
    # Silurian
    "Silurian",
    "Llandovery",
    "Wenlock",
    "Ludlow",
    "Pridoli",
    # Devonian
    "Devonian",
    "Lochkovian",
    "Pragian",
    "Emsian",
    "Eifelian",
    "Givetian",
    "Frasnian",
    "Famennian",
    # Carboniferous
    "Carboniferous",
    "Mississippian",
    "Tournaisian",
    "Visean",
    "Serpukhovian",
    "Pennsylvanian",
    "Bashkirian",
    "Moscovian",
    "Gzhelian",
    # Permian
    "Permian",
    "Cisuralian",
    "Asselian",
    "Kungurian",
    "Guadalupian",
    "Roadian",
    "Capitanian",
    "Lopingian",
    "Changhsingian",
    # Triassic
    "Triassic",
    "Trias",
    "Induan",
    "Olenekian",
    "Anisian",
    "Ladinian",
    "Carnian",
    "Norian",
    "Rhaetian",
    # Jurassic
    "Jurassic",
    "Hettangian",
    "Sinemurian",
    "Pliensbachian",
    "Toarcian",
    "Bajocian",
    "Bathonian",
    "Callovian",
    "Oxfordian",
    "Kimmeridgian",
    "Tithonian",
    # Cretaceous
    "Cretaceous",
    "Berriasian",
    "Valanginian",
    "Hauterivian",
    "Barremian",
    "Aptian",
    "Albian",
    "Cenomanian",
    "Turonian",
    "Santonian",
    "Campanian",
    "Maastrichtian",
    # Paleogene
    "Paleogene",
    "Paleocene",
    "Danian",
    "Thanetian",
    "Eocene",
    "Ypresian",
    "Lutetian",
    "Priabonian",
    "Oligocene",
    "Rupelian",
    "Chattian",
    # Neogene
    "Neogene",
    "Miocene",
    "Aquitanian",
    "Burdigalian",
    "Serravallian",
    "Messinian",
    "Pliocene",
    "Zanclean",
    "Piacenzian",
    # Quaternary
    "Quaternary",
    "Pleistocene",
    "Gelasian",
    "Calabrian",
    "Chibanian",
    "Tarantian",
    "Holocene",
    "Greenlandian",
    "Northgrippian",
    "Meghalayan",
    "Anthropocene",
]


def get_next_epoch(current: Optional[str] = None) -> str:
    """Return the next chronological epoch following `current`.
    Defaults to Devonian if current is Silurian or not found.
    """
    if not current:
        return "Devonian"

    curr_lower = current.strip().lower()
    
    # Try exact or case-insensitive match
    for idx, name in enumerate(EARTH_EPOCHS):
        if name.lower() == curr_lower:
            if idx + 1 < len(EARTH_EPOCHS):
                return EARTH_EPOCHS[idx + 1]
            return "Post-Anthropocene"

    # Common period defaults
    period_sequence = [
        "Ordovician", "Silurian", "Devonian", "Carboniferous", "Permian",
        "Triassic", "Jurassic", "Cretaceous", "Paleogene", "Neogene", "Quaternary"
    ]
    for idx, p in enumerate(period_sequence):
        if p.lower() == curr_lower or (curr_lower == "trias" and p == "Triassic"):
            if idx + 1 < len(period_sequence):
                return period_sequence[idx + 1]

    return "Devonian"
