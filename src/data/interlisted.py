# -*- coding: utf-8 -*-
"""Interlisted companies: one company listed on the TSX and on a US exchange.

Each pair is ``(TSX symbol, US symbol)``: two separate listings, each with its own
exchange and trading currency (TSX in CAD, the US listing in USD), linked to one
company. A company name alone never chooses between them
(``src/services/english_stock_names.py``); the user enters the symbol.

Reviewed by hand on 2026-10-12 against the bundled stock index
(``apps/dsa-web/public/stocks.index.json``); ``scripts/suggest_interlisted_pairs.py``
lists the candidates to review when the index changes. Rules:

- both symbols are in the index; the US listing is on NYSE, Nasdaq or NYSE American
  (OTC quotes are not interlisted listings);
- the same share class on both sides (``TECK-B.TO``/``TECK`` are both class B);
  depositary receipts (``LOBLY``) and other securities (``AQNU`` units) are excluded;
- a shared ticker is not enough: ``T.TO`` is TELUS but ``T`` is AT&T, and TELUS
  trades in the US as ``TU``.
"""

from typing import Tuple

INTERLISTED_PAIRS: Tuple[Tuple[str, str], ...] = (
    # Same ticker on both exchanges.
    ("AAUC.TO", "AAUC"),  # Allied Gold
    ("AEM.TO", "AEM"),  # Agnico Eagle Mines
    ("AG.TO", "AG"),  # First Majestic Silver
    ("AGI.TO", "AGI"),  # Alamos Gold
    ("AQN.TO", "AQN"),  # Algonquin Power & Utilities
    ("ASM.TO", "ASM"),  # Avino Silver & Gold Mines
    ("ATS.TO", "ATS"),  # ATS Corporation
    ("BAM.TO", "BAM"),  # Brookfield Asset Management
    ("BB.TO", "BB"),  # BlackBerry
    ("BBUC.TO", "BBUC"),  # Brookfield Business Corporation
    ("BCE.TO", "BCE"),  # BCE
    ("BHC.TO", "BHC"),  # Bausch Health
    ("BMO.TO", "BMO"),  # Bank of Montreal
    ("BN.TO", "BN"),  # Brookfield Corporation
    ("BNS.TO", "BNS"),  # Bank of Nova Scotia
    ("BTE.TO", "BTE"),  # Baytex Energy
    ("CAE.TO", "CAE"),  # CAE
    ("CIGI.TO", "CIGI"),  # Colliers International
    ("CLS.TO", "CLS"),  # Celestica
    ("CM.TO", "CM"),  # CIBC
    ("CNQ.TO", "CNQ"),  # Canadian Natural Resources
    ("CP.TO", "CP"),  # Canadian Pacific Kansas City
    ("CVE.TO", "CVE"),  # Cenovus Energy
    ("EFX.TO", "EFX"),  # Equifax
    ("EMA.TO", "EMA"),  # Emera
    ("ENB.TO", "ENB"),  # Enbridge
    ("EQX.TO", "EQX"),  # Equinox Gold
    ("ERO.TO", "ERO"),  # Ero Copper
    ("FNV.TO", "FNV"),  # Franco-Nevada
    ("FSV.TO", "FSV"),  # FirstService
    ("FTS.TO", "FTS"),  # Fortis
    ("GFL.TO", "GFL"),  # GFL Environmental
    ("GIL.TO", "GIL"),  # Gildan Activewear
    ("HBM.TO", "HBM"),  # Hudbay Minerals
    ("IMO.TO", "IMO"),  # Imperial Oil
    ("LAC.TO", "LAC"),  # Lithium Americas
    ("LSPD.TO", "LSPD"),  # Lightspeed Commerce
    ("MFC.TO", "MFC"),  # Manulife Financial
    ("NG.TO", "NG"),  # NovaGold Resources
    ("NTR.TO", "NTR"),  # Nutrien
    ("NXE.TO", "NXE"),  # NexGen Energy
    ("OR.TO", "OR"),  # OR Royalties (formerly Osisko Gold Royalties)
    ("OTEX.TO", "OTEX"),  # Open Text
    ("PAAS.TO", "PAAS"),  # Pan American Silver
    ("PPTA.TO", "PPTA"),  # Perpetua Resources
    ("QSR.TO", "QSR"),  # Restaurant Brands International
    ("RBA.TO", "RBA"),  # RB Global
    ("RY.TO", "RY"),  # Royal Bank of Canada
    ("SHOP.TO", "SHOP"),  # Shopify
    ("SII.TO", "SII"),  # Sprott
    ("SKE.TO", "SKE"),  # Skeena Resources
    ("SLF.TO", "SLF"),  # Sun Life Financial
    ("SOBO.TO", "SOBO"),  # South Bow
    ("SSRM.TO", "SSRM"),  # SSR Mining
    ("STN.TO", "STN"),  # Stantec
    ("SU.TO", "SU"),  # Suncor Energy
    ("SVM.TO", "SVM"),  # Silvercorp Metals
    ("TD.TO", "TD"),  # Toronto-Dominion Bank
    ("TFII.TO", "TFII"),  # TFI International
    ("TFPM.TO", "TFPM"),  # Triple Flag Precious Metals
    ("TRI.TO", "TRI"),  # Thomson Reuters
    ("TRP.TO", "TRP"),  # TC Energy
    ("VET.TO", "VET"),  # Vermilion Energy
    ("VZLA.TO", "VZLA"),  # Vizsla Silver
    ("WCN.TO", "WCN"),  # Waste Connections
    ("WFG.TO", "WFG"),  # West Fraser Timber
    ("WPM.TO", "WPM"),  # Wheaton Precious Metals
    # Different tickers.
    ("ABX.TO", "B"),  # Barrick Mining
    ("ARIS.TO", "ARMN"),  # Aris Mining (US ARIS is Aris Water Solutions)
    ("BEP-UN.TO", "BEP"),  # Brookfield Renewable Partners (units)
    ("BIP-UN.TO", "BIP"),  # Brookfield Infrastructure Partners (units)
    ("BTO.TO", "BTG"),  # B2Gold
    ("CCO.TO", "CCJ"),  # Cameco (US CCO is Clear Channel Outdoor)
    ("CG.TO", "CGAU"),  # Centerra Gold (US CG is Carlyle)
    ("CNR.TO", "CNI"),  # Canadian National Railway
    ("DML.TO", "DNN"),  # Denison Mines
    ("DOO.TO", "DOOO"),  # BRP
    ("DSG.TO", "DSGX"),  # Descartes Systems Group
    ("EDR.TO", "EXK"),  # Endeavour Silver
    ("EFR.TO", "UUUU"),  # Energy Fuels
    ("ELD.TO", "EGO"),  # Eldorado Gold
    ("FVI.TO", "FSM"),  # Fortuna Mining
    ("GIB-A.TO", "GIB"),  # CGI (class A)
    ("IAU.TO", "IAUX"),  # i-80 Gold
    ("IMG.TO", "IAG"),  # IAMGOLD (TSX IAG.TO is iA Financial)
    ("K.TO", "KGC"),  # Kinross Gold
    ("MG.TO", "MGA"),  # Magna International
    ("MX.TO", "MEOH"),  # Methanex
    ("PPL.TO", "PBA"),  # Pembina Pipeline (US PPL is PPL Corporation)
    ("RCI-B.TO", "RCI"),  # Rogers Communications (class B)
    ("SEA.TO", "SA"),  # Seabridge Gold
    ("T.TO", "TU"),  # TELUS (US T is AT&T)
    ("TA.TO", "TAC"),  # TransAlta
    ("TECK-B.TO", "TECK"),  # Teck Resources (class B)
    ("TKO.TO", "TGB"),  # Taseko Mines
    ("USA.TO", "USAS"),  # Americas Gold and Silver
)
