# POC DLP - IA

Prototype de détection et classification de données sensibles dans des documents
(Word, PDF, e-mails, XML et archives ZIP), avec scoring de risque, règles de
blocage C1-C4 et tableau de bord.

## Structure du projet

```
dlp-poc/
├── src/
│   ├── extraction.py       # lecture Word/PDF/texte
│   ├── classification.py   # classification C1-C4 (règles + CamemBERT)
│   ├── scoring.py          # calcul du score de risque + alerte
│   └── dashboard.py        # tableau de bord Streamlit
├── data/                   # dataset (non versionné, voir .gitignore)
├── notebooks/               # exploration & entraînement du modèle
├── models/                 # modèles entraînés sauvegardés
├── requirements.txt
└── README.md
```

## Installation

```bash
python -m venv venv_dlp
venv_dlp\Scripts\activate        # Windows
pip install -r requirements.txt
```

## Lancer le dashboard

```bash
streamlit run src/dashboard.py
```

## Tester les modules individuellement

```bash
python src/extraction.py
python src/classification.py
python src/scoring.py
```

## Formats et sécurité d'analyse

Les fichiers `.docx`, `.pdf`, `.eml`, `.txt`, `.csv`, `.json`, `.log`, `.md`,
`.xml` et `.zip` sont pris en charge. Les ZIP sont lus en mémoire uniquement :
le projet limite le nombre d'entrées, la taille décompressée et la profondeur
d'imbrication afin de ne pas extraire de fichiers non fiables sur le poste.
Les XML contenant une DTD ou des entités sont refusés.

## Trajectoire Microsoft 365 / Purview

Un guide de préparation et de test en environnement isolé est disponible dans
[`docs/M365_LAB_GUIDE.md`](docs/M365_LAB_GUIDE.md).

Le mode M365 reste en simulation par défaut. Il ne crée ni n'active aucune
politique dans le tenant. L'onglet **Trajectoire M365** fournit un modèle de
politique C1-C4 à faire valider par le RSSI/DPO.

Pour un pilote contrôlé uniquement : copiez `.env.example` vers `.env`,
renseignez un compte de test dans `GRAPH_TARGET_USER` et les destinataires
d'alerte dans `DLP_ALERT_RECIPIENTS`, puis passez `microsoft365.enabled` à
`true` dans `config.yaml`. Gardez les politiques Purview en simulation durant
le pilote. Utilisez le moindre privilège et limitez l'application à
une boîte, un site SharePoint et un OneDrive pilotes avant tout blocage. Pour
l'envoi d'alertes, ajoutez également la permission applicative `Mail.Send` et
son consentement administrateur.

## Tests

```bash
python -m unittest discover -s tests -v
```
