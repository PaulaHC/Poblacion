PROVINCIAS: dict[str, tuple[str, str, str]] = {
    "01": ("Álava",                    "País Vasco",                "PV"),
    "02": ("Albacete",                 "Castilla-La Mancha",        "CLM"),
    "03": ("Alicante",                 "Comunitat Valenciana",      "CV"),
    "04": ("Almería",                  "Andalucía",                 "AND"),
    "05": ("Ávila",                    "Castilla y León",           "CyL"),
    "06": ("Badajoz",                  "Extremadura",               "EXT"),
    "07": ("Baleares",                 "Islas Baleares",             "IB"),
    "08": ("Barcelona",                "Cataluña",                 "CAT"),
    "09": ("Burgos",                   "Castilla y León",           "CyL"),
    "10": ("Cáceres",                  "Extremadura",               "EXT"),
    "11": ("Cádiz",                    "Andalucía",                 "AND"),
    "12": ("Castellón",                "Comunitat Valenciana",      "CV"),
    "13": ("Ciudad Real",              "Castilla-La Mancha",        "CLM"),
    "14": ("Córdoba",                  "Andalucía",                 "AND"),
    "15": ("La Coruña",                "Galicia",                   "GAL"),
    "16": ("Cuenca",                   "Castilla-La Mancha",        "CLM"),
    "17": ("Gerona",                   "Catalunya",                 "CAT"),
    "18": ("Granada",                  "Andalucía",                 "AND"),
    "19": ("Guadalajara",              "Castilla-La Mancha",        "CLM"),
    "20": ("Guipúzcoa",                "País Vasco",                "PV"),
    "21": ("Huelva",                   "Andalucía",                 "AND"),
    "22": ("Huesca",                   "Aragón",                    "ARA"),
    "23": ("Jaén",                     "Andalucía",                 "AND"),
    "24": ("León",                     "Castilla y León",           "CyL"),
    "25": ("Lérida",                   "Catalunya",                 "CAT"),
    "26": ("La Rioja",                 "La Rioja",                  "LR"),
    "27": ("Lugo",                     "Galicia",                   "GAL"),
    "28": ("Madrid",                   "Comunidad de Madrid",       "MAD"),
    "29": ("Málaga",                   "Andalucía",                 "AND"),
    "30": ("Murcia",                   "Región de Murcia",          "MUR"),
    "31": ("Navarra",                  "Comunidad Foral de Navarra","NAV"),
    "32": ("Orense",                   "Galicia",                   "GAL"),
    "33": ("Asturias",                 "Principado de Asturias",    "AST"),
    "34": ("Palencia",                 "Castilla y León",           "CyL"),
    "35": ("Las Palmas",               "Canarias",                  "CAN"),
    "36": ("Pontevedra",               "Galicia",                   "GAL"),
    "37": ("Salamanca",                "Castilla y León",           "CyL"),
    "38": ("Santa Cruz de Tenerife",   "Canarias",                  "CAN"),
    "39": ("Cantabria",                "Cantabria",                 "CANT"),
    "40": ("Segovia",                  "Castilla y León",           "CyL"),
    "41": ("Sevilla",                  "Andalucía",                 "AND"),
    "42": ("Soria",                    "Castilla y León",           "CyL"),
    "43": ("Tarragona",                "Catalunya",                 "CAT"),
    "44": ("Teruel",                   "Aragón",                    "ARA"),
    "45": ("Toledo",                   "Castilla-La Mancha",        "CLM"),
    "46": ("Valencia",                 "Comunitat Valenciana",      "CV"),
    "47": ("Valladolid",               "Castilla y León",           "CyL"),
    "48": ("Vizcaya",                  "País Vasco",                "PV"),
    "49": ("Zamora",                   "Castilla y León",           "CyL"),
    "50": ("Zaragoza",                 "Aragón",                    "ARA"),
    "51": ("Ceuta",                    "Ceuta",  "CEU"),
    "52": ("Melilla",                  "Melilla", "MEL"),
}

DATASETS = {
    "poblacion": {
        # Padrón municipal — población por municipio y sexo (1996-2025)
        # Una tabla por provincia (52 tablas)
        "municipios": [
            "2855", "2856", "2857", "2854", "2886", "2858",
            "2859", "2860", "2861", "2905", "2862", "2863",
            "2864", "2893", "2865", "2866", "2901", "2868",
            "2869", "2873", "2870", "2871", "2872", "2874",
            "2875", "2876", "2877", "2878", "2880", "2881",
            "2882", "2883", "2884", "2885", "2888", "2889",
            "2890", "2879", "2891", "2892", "2894", "2895",
            "2896", "2900", "2899", "2902", "2903", "2904",
            "2906", "2907", "2908", "2909",
        ],
        # Edad mediana por municipio y sexo (2014-2025)
        "edad_mediana": ["30700"],
        # Migración: municipio × nacionalidad (español/extranjero) × edad
        "migracion": ["33571"],
        # Natalidad: tasa bruta por municipio
        "natalidad": ["78770"],
        # Fecundidad: tasa global por municipio
        "fecundidad": ["30665"],
        # Mortalidad: tasas por municipio, sexo y grupo de edad
        "mortalidad": ["78775"],
        # Esperanza de vida — tabla separada, campo = años de vida (no tasa)
        "esperanza_vida": ["30687"],
        # Empresas por municipio y actividad CNAE principal
        "trabajo": ["4721"],
        # Nivel de estudios:
        #   66620 → municipios ≥ 500 hab (tiene grupo_edad)
        #   66623 → municipios 50-500 hab (sin grupo_edad)
        "estudios": ["66620", "66623"],
        # Estado civil:
        #   76306 → municipios ≥ 500 hab (tiene grupo_edad)
        #   76312 → municipios 50-500 hab (sin grupo_edad)
        "estadoCivil": ["76306", "76312"],
        # Renta por hogar por municipio (sin sexo ni edad):
        "renta": ["31097"],
    }
}