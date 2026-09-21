"""Tabla de alias de equipos y normalización de nombres para cruzar eventos entre
casas de apuestas.

Comparar nombres de equipo por similitud de texto genérica es insuficiente
para clubes españoles: "Barcelona" y "Celta" comparten suficientes letras en
común (ratio ~0.57) como para confundirse, y "Atlético Madrid" / "Real
Madrid" comparten literalmente la palabra "Madrid". Una tabla de alias curada a
mano es más fiable que cualquier heurística de similitud, así que las ligas
grandes (LaLiga, Premier, Serie A, Bundesliga, Ligue 1, Portugal, Países Bajos,
Champions, Argentina, Brasil, México) se listan aquí.

Para todo lo demás (ligas menores, Colombia, Chile, Perú...) `squash` normaliza
el nombre a palabras significativas (sin "FC", "CD", "Club"...; con "Dep."/"Utd"
expandidos, selecciones en inglés, marcas de sub-23/reserva/femenino aparte) y
engine/matching.py compara esas palabras con reglas estrictas. Verificado el
2026-09-21 con partidos reales de Altenar y Kambi a la misma hora: solo el 46 %
de los pares cruzaban con la tabla antigua (LaLiga + similitud de texto).

Cada variante va normalizada (ver `normalize`: minúsculas, sin acentos, solo
alfanumérico), tal como las emiten los proveedores. Ampliar esta tabla al añadir
más casas o más ligas; una variante NO puede estar en dos grupos (lo comprueba
tests/test_matching.py).
"""

import re
import unicodedata
from functools import lru_cache


@lru_cache(maxsize=None)
def normalize(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"[^a-z0-9 ]", "", name.lower())
    return re.sub(r"\s+", " ", name).strip()


# Cada línea es un club: variantes separadas por "|"; la primera es el id canónico.
_CLUBS = """
atletico madrid|atletico de madrid|at madrid|atl madrid|atletico
real madrid|r madrid
barcelona|fc barcelona
barcelona sc|barcelona guayaquil|barcelona de guayaquil|barcelona sporting club
celta|celta vigo|celta de vigo
racing santander|racing s|racing de santander|r santander
osasuna|ca osasuna
sevilla|sevilla fc
deportivo|deportivo la coruna|deportivo de a coruna|rc deportivo
levante|levante ud
athletic|athletic bilbao|athletic de bilbao|ath bilbao|athletic club
real betis|betis
getafe|getafe cf
malaga|malaga cf
villarreal|villarreal cf
espanyol|rcd espanyol
elche|elche cf
rayo vallecano|rayo v|rayo
alaves|deportivo alaves
valencia|valencia cf
real sociedad|r sociedad
mallorca|rcd mallorca
girona|girona fc
real valladolid|valladolid
las palmas|ud las palmas
leganes|cd leganes
granada|granada cf
almeria|ud almeria
cadiz|cadiz cf
sporting gijon|real sporting|sporting de gijon
real zaragoza|zaragoza
real oviedo|oviedo
eibar|sd eibar
tenerife|cd tenerife
burgos|burgos cf

manchester city|man city|mancity
manchester united|man united|man utd|manchester utd
tottenham|tottenham hotspur|spurs
wolverhampton|wolves|wolverhampton wanderers
newcastle|newcastle united|newcastle utd
nottingham forest|nottm forest|nott forest
west ham|west ham united|west ham utd
brighton|brighton hove albion|brighton and hove albion
leicester|leicester city
leeds|leeds united|leeds utd
sheffield united|sheffield utd
crystal palace
aston villa
bournemouth|afc bournemouth
west bromwich albion|west brom|west bromwich
ipswich|ipswich town
norwich|norwich city
middlesbrough|boro

inter|inter milan|internazionale|internazionale milano|inter de milan
milan|ac milan|a c milan
juventus|juve|juventus turin
roma|as roma
lazio|ss lazio
napoli|ssc napoli
atalanta|atalanta bc|atalanta bergamo
fiorentina|acf fiorentina
verona|hellas verona|hellas
chievo|chievo verona
parma|parma calcio

bayern munich|bayern munchen|fc bayern munchen|bayern|bayern munich fc
borussia dortmund|dortmund|b dortmund|bvb
bayer leverkusen|leverkusen|bayer 04 leverkusen|bayer 04
borussia monchengladbach|monchengladbach|b monchengladbach|gladbach|borussia m gladbach|m gladbach
rb leipzig|leipzig|rasenballsport leipzig
eintracht frankfurt|frankfurt|e frankfurt
wolfsburg|vfl wolfsburg
freiburg|sc freiburg
mainz|mainz 05|fsv mainz 05|1 fsv mainz 05
union berlin|1 fc union berlin
stuttgart|vfb stuttgart
hoffenheim|tsg hoffenheim|tsg 1899 hoffenheim
werder bremen|werder|sv werder bremen
augsburg|fc augsburg
heidenheim|1 fc heidenheim|fc heidenheim
st pauli|fc st pauli|sankt pauli
koln|fc koln|1 fc koln|cologne
hamburger sv|hamburg|hsv

paris saint germain|paris sg|psg|paris st germain|paris saintgermain
marseille|olympique marseille|olympique de marseille
lyon|olympique lyonnais|olympique lyon
monaco|as monaco
lille|losc lille|losc
nice|ogc nice
lens|rc lens
rennes|stade rennais|stade rennes
reims|stade de reims|stade reims
strasbourg|rc strasbourg
montpellier|montpellier hsc
brest|stade brestois|stade brestois 29
angers|angers sco
le havre|le havre ac

ajax|afc ajax
psv|psv eindhoven
az alkmaar|az
twente|fc twente
benfica|sl benfica|s l benfica
porto|fc porto
sporting cp|sporting lisbon|sporting lisboa|sporting clube de portugal|sporting cp lisbon
braga|sporting braga|sc braga|s c braga

celtic|celtic glasgow
rangers|glasgow rangers
galatasaray|galatasaray sk
fenerbahce|fenerbahce sk
besiktas|besiktas jk
olympiacos|olympiakos|olympiacos piraeus
club brugge|club bruges|brugge|fc brugge
anderlecht|rsc anderlecht
salzburg|red bull salzburg|rb salzburg|fc salzburg
shakhtar donetsk|shakhtar
dinamo zagreb|gnk dinamo zagreb|dynamo zagreb
copenhagen|fc copenhagen|fc kobenhavn|kobenhavn
slavia praga|slavia prague|slavia praha|sk slavia praha
sparta praga|sparta prague|sparta praha|ac sparta praha
red star belgrade|crvena zvezda|estrella roja|estrella roja belgrado

river plate|ca river plate|river
boca juniors|boca|ca boca juniors
racing club|racing club avellaneda|racing avellaneda
independiente|ca independiente|independiente avellaneda
independiente rivadavia|ind rivadavia|independiente rivadavia mendoza
san lorenzo|ca san lorenzo|san lorenzo de almagro
estudiantes|estudiantes la plata|estudiantes de la plata
velez sarsfield|velez|ca velez sarsfield
talleres|talleres cordoba|talleres de cordoba
newells old boys|newells
argentinos juniors|argentinos jrs|argentinos
rosario central|ca rosario central
lanus|ca lanus
huracan|ca huracan
barracas central|ca barracas central
central cordoba|central cordoba sde|central cordoba de santiago del estero

flamengo|cr flamengo|flamengo rj
palmeiras|se palmeiras
corinthians|sc corinthians|corinthians sp
sao paulo|sao paulo fc
santos fc|santos sp
fluminense|fluminense fc|fluminense rj
botafogo|botafogo rj|botafogo fr
vasco da gama|vasco|cr vasco da gama
atletico mineiro|atletico mg|clube atletico mineiro|atl mineiro
cruzeiro|cruzeiro mg|cruzeiro ec
gremio|gremio porto alegre|gremio fbpa
internacional|sc internacional|internacional rs|internacional porto alegre
bahia|ec bahia|bahia ba|ec bahia ba
fortaleza|fortaleza ec

club america|america mexico
guadalajara|chivas|cd guadalajara|chivas guadalajara
pumas unam|unam pumas|pumas|club universidad nacional
tigres uanl|uanl tigres|tigres de la uanl
monterrey|cf monterrey|rayados
cruz azul|cd cruz azul
toluca|deportivo toluca
santos laguna
queretaro|queretaro fc
tijuana|club tijuana|xolos
"""

_CLUB_GROUPS: list[tuple[str, ...]] = [
    tuple(variant.strip() for variant in line.split("|")) for line in _CLUBS.strip().splitlines() if line.strip()
]

# Selecciones: nombre en español (o variante) -> nombre en inglés. Se aplica sobre
# el nombre completo ya sin marca de edad ("Corea del Sur Sub-23" -> "south korea").
_COUNTRIES = {
    "corea del sur": "south korea", "corea del norte": "north korea", "arabia saudi": "saudi arabia",
    "arabia saudita": "saudi arabia", "filipinas": "philippines", "estados unidos": "usa", "eeuu": "usa",
    "united states": "usa", "inglaterra": "england", "alemania": "germany", "francia": "france",
    "italia": "italy", "paises bajos": "netherlands", "holanda": "netherlands", "belgica": "belgium",
    "croacia": "croatia", "dinamarca": "denmark", "suecia": "sweden", "noruega": "norway", "suiza": "switzerland",
    "polonia": "poland", "republica checa": "czech republic", "chequia": "czech republic", "turquia": "turkey",
    "japon": "japan", "marruecos": "morocco", "egipto": "egypt", "tunez": "tunisia", "argelia": "algeria",
    "sudafrica": "south africa", "brasil": "brazil", "irak": "iraq", "emiratos arabes unidos": "united arab emirates",
    "emiratos arabes": "united arab emirates", "catar": "qatar", "jordania": "jordan", "tailandia": "thailand",
    "escocia": "scotland", "gales": "wales", "irlanda": "ireland", "irlanda del norte": "northern ireland",
    "grecia": "greece", "rusia": "russia", "ucrania": "ukraine", "rumania": "romania", "hungria": "hungary",
    "finlandia": "finland", "islandia": "iceland", "eslovaquia": "slovakia", "eslovenia": "slovenia",
    "bosnia herzegovina": "bosnia herzegovina", "camerun": "cameroon", "costa de marfil": "ivory coast",
    "nueva zelanda": "new zealand", "malasia": "malaysia", "singapur": "singapore", "barein": "bahrain",
    "siria": "syria", "libano": "lebanon", "palestina": "palestine", "chipre": "cyprus", "luxemburgo": "luxembourg",
    "letonia": "latvia", "lituania": "lithuania", "bielorrusia": "belarus", "moldavia": "moldova",
    "macedonia del norte": "north macedonia", "azerbaiyan": "azerbaijan", "kazajistan": "kazakhstan",
    "republica dominicana": "dominican republic", "trinidad y tobago": "trinidad tobago",
}

# Palabras que no distinguen a un equipo de otro (formas jurídicas, "Club", artículos).
_STOP = frozenset(
    "fc cf ac sc cd ud ad sd fk sk sv vfb vfl fsv tsg bsc afc ssc as us ss kv ks nk hnk gnk club de del la el los las "
    "the of da do di dos and y al calcio ca cs cfr asociacion deportiva".split()
)
# Abreviaturas -> palabra completa.
_TOKEN_ALIASES = {
    "utd": "united", "dep": "deportivo", "depor": "deportivo", "intl": "internacional", "int": "internacional",
    "atl": "atletico", "ath": "athletic", "st": "saint", "sankt": "saint", "man": "manchester",
}
# Palabras que por sí solas no identifican un equipo (hay decenas de "Independiente",
# "Sporting", "Real"...): un nombre formado SOLO por ellas no se acepta como versión
# abreviada de otro más largo.
GENERIC = frozenset(
    "independiente nacional sporting atletico deportivo universidad union racing real dinamo dynamo inter internacional "
    "olimpia central athletic sport rovers city united town wanderers rangers juventud america olympic olympique "
    "estudiantes argentinos defensa municipal americano alianza colon libertad cerro saint".split()
)

# Palabras que delatan un filial/cantera ("Portadown FC Reserve", "Linfield Swifts").
_RESERVE_WORDS = frozenset("reserve reserves res youth academy juvenil filial swifts".split())
# Selecciones (en inglés): una selección solo casa con el mismo nombre exacto, nunca
# como versión abreviada de otro equipo ("England" no es "New England Revolution").
COUNTRY_NAMES = frozenset(_COUNTRIES.values()) | frozenset(
    "spain portugal mexico peru chile colombia argentina uruguay paraguay ecuador bolivia venezuela canada iran "
    "japan china india australia nigeria ghana senegal serbia austria albania bulgaria georgia armenia israel kuwait "
    "uzbekistan indonesia vietnam jamaica haiti panama honduras guatemala cuba".split()
)

_AGE_RE = re.compile(r"\b(?:u|sub|under)[\s-]?(\d{2})\b")
_WOMEN_RE = re.compile(r"\((?:w|f)\)|\bwomen\b|\bfem\b|\bfemenil\b|\bfemenino\b|\bfeminas\b")


def _build_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for group in _CLUB_GROUPS:
        for variant in group:
            index[variant] = group[0]
    return index


_VARIANT_INDEX = _build_index()


@lru_cache(maxsize=None)
def squash(name: str) -> tuple[tuple[str, ...], frozenset[str]]:
    """(palabras significativas, marcas) de un nombre de equipo. Las marcas
    ("u23", "w", "2", "b", "ii") distinguen equipos base de sub-23, femeninos y
    filiales: dos nombres solo pueden ser el mismo equipo si tienen las MISMAS marcas.
    """
    text = name.lower()
    markers: set[str] = set()
    for match in _AGE_RE.finditer(text):
        markers.add("u" + match.group(1))
    text = _AGE_RE.sub(" ", text)
    if _WOMEN_RE.search(text):
        markers.add("w")
        text = _WOMEN_RE.sub(" ", text)
    # Etiqueta entre paréntesis que no es "(W)"/"(F)": nombre de jugador de un
    # partido de e-soccer ("Liverpool (Nairo)") u otra aclaración; nunca es el
    # equipo "a secas".
    for tag in re.findall(r"\(([^)]*)\)", text):
        markers.add("p:" + normalize(tag))
    text = re.sub(r"\([^)]*\)", " ", text)
    norm = normalize(text)
    norm = _COUNTRIES.get(norm, norm)
    kept: list[str] = []
    for i, token in enumerate(norm.split()):
        token = _TOKEN_ALIASES.get(token, token)
        if token in _STOP:
            continue
        if token.isdigit():
            if i > 0 and len(token) == 1:  # "Ranheim 2" es un filial; "Mainz 05", "1899", "1. FC Köln" no
                markers.add(token)
            continue
        if i > 0 and token in ("ii", "iii", "b", "c"):
            markers.add(token)
            continue
        if token in _RESERVE_WORDS:
            markers.add("res")
            continue
        kept.append(token)
    return tuple(kept), frozenset(markers)


def canonical_team(name: str) -> str | None:
    """Id canónico de un club de la tabla, o None si no está (equipo de otra
    liga/deporte no cubierto). `name` es el nombre original (los paréntesis de
    "(W)" se pierden al normalizar). Reconoce la variante exacta o, si no, el
    nombre ya sin "FC"/"CD"...; con marcas (filial, sub-23, femenino) el id las
    lleva detrás, así que "Barcelona B" nunca es "Barcelona".
    """
    tokens, markers = squash(name)
    canon = _VARIANT_INDEX.get(normalize(name)) if not markers else None
    if canon is None:
        canon = _SQUASHED_INDEX.get(" ".join(tokens))
    if canon is None:
        return None
    return canon + "".join(f"|{m}" for m in sorted(markers)) if markers else canon


def _build_squashed_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for group in _CLUB_GROUPS:
        for variant in group:
            tokens, markers = squash(variant)
            if not markers and tokens:
                index.setdefault(" ".join(tokens), group[0])
    return index


_SQUASHED_INDEX = _build_squashed_index()
