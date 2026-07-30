# POC DLP intelligent basé sur l’IA et Microsoft Purview

Ce dépôt contient un Proof of Concept de prévention de fuite de données sensibles
(DLP) destiné à simuler une logique de classification, de scoring et de gouvernance
à partir de documents métier. Le projet a été conçu dans un cadre de stage pour
illustrer une trajectoire réaliste vers Microsoft Purview tout en restant dans un
mode de simulation autonome et conforme au cahier des charges.

## Objectif du projet

Le POC permet de :
- extraire le contenu textuel de documents Word, PDF, texte, e-mails et archives ZIP ;
- détecter des données sensibles (personnelles, médicales, financières, RH, juridiques, stratégiques) ;
- attribuer un niveau de confidentialité C1 à C4 ;
- calculer un score de risque et déclencher des alertes DLP simulées ;
- appliquer des règles de transfert et d’usage cohérentes avec une politique COMAR ;
- présenter les résultats dans un tableau de bord Streamlit destiné au RSSI, au DPO et aux équipes conformité.

## Architecture du projet

```text
dlp-poc/
├── src/
│   ├── classification.py   # classification C1-C4 et justification explicite
│   ├── dashboard.py        # interface Streamlit d’analyse et de simulation
│   ├── extraction.py       # extraction de texte depuis plusieurs formats
│   ├── generate_dataset.py # génération et anonymisation du dataset
│   ├── m365_integration.py # préparation d’intégration Microsoft 365 / Purview
│   ├── policy.py           # règles DLP pour actions et transferts
│   ├── scoring.py          # calcul du score de risque
│   ├── taxonomy.py         # référentiel métier et cartographie des données sensibles
│   └── train_camembert.py  # entraînement du modèle CamemBERT
├── data/
│   └── dataset.csv         # jeu de données anonymisé et labellisé
├── docs/
│   └── M365_LAB_GUIDE.md   # guide de préparation Purview en environnement isolé
├── models/                 # modèles entraînés et checkpoints
├── tests/                  # tests de validation des modules clés
├── requirements.txt
└── README.md
```

## Fonctionnement principal

1. Extraction du texte depuis le document fourni.
2. Classification automatique du document selon les niveaux :
   - C1 : Public
   - C2 : Interne
   - C3 : Confidentiel
   - C4 : Hautement confidentiel
3. Détection des éléments sensibles et génération d’une justification explicite.
4. Calcul d’un score de risque et déclenchement d’alertes si nécessaire.
5. Application d’une politique DLP simulée pour les actions et transferts.
6. Affichage dans un tableau de bord professionnel.

## Dataset et anonymisation

Le dataset est généré et anonymisé pour respecter un usage pédagogique et conforme
au cahier de charge du stage. Les exemples contiennent des placeholders tels que
[PERSONNE], [IDENTIFIANT], [SERVICE] ou [DONNEES] afin d’éviter toute exposition
de données réelles.

Pour régénérer le dataset :

```bash
python src/generate_dataset.py
```

## Installation

Sous Windows :

```bash
python -m venv venv_dlp
venv_dlp\Scripts\activate
pip install -r requirements.txt
```

## Lancer l’application

```bash
streamlit run src/dashboard.py
```

## Tests

```bash
python -m unittest discover -s tests -v
```

## Trajectoire Microsoft 365 / Purview

Le projet reste volontairement en mode simulation par défaut. Il ne crée ni n’active
aucune politique réelle sur un tenant Microsoft 365 tant qu’aucune configuration
pilote n’est explicitement fournie.

Le guide de préparation est disponible dans [docs/M365_LAB_GUIDE.md](docs/M365_LAB_GUIDE.md).
Cette préparation est pensée pour une future intégration dans Microsoft Purview,
avec validation RSSI/DPO et respect du moindre privilège.

## Limites du POC

Ce projet est un prototype de démonstration, pas une solution de production.
Les règles actuelles sont orientées simulation, pédagogie et validation fonctionnelle,
avec un focus sur l’alignement du cahier de charge de stage.

