# Guide de test Microsoft 365 / Purview DLP

## Objectif et sécurité

Tester uniquement dans un tenant de démonstration, jamais dans le tenant COMAR
ni avec des données réelles. Utiliser des comptes et des documents fictifs.
Commencer en mode **simulation**, sans blocage.

## Obtenir un lab

1. Créer ou utiliser un compte de développement Microsoft 365 Developer Program.
2. Si l'éligibilité est accordée, créer le sandbox Microsoft 365 E5 développeur
   (jusqu'à 25 licences, durée maximale de 90 jours avec renouvellement selon
   l'activité de développement).
3. Créer trois utilisateurs : `dlp-admin`, `pilote-a` et `pilote-b`.
4. Activer MFA pour l'administrateur et ne pas réutiliser de compte de
   production.

L'accès gratuit n'est pas garanti : il dépend de l'éligibilité du Developer
Program. À défaut, conserver le POC local en simulation ou demander un tenant
E5 d'essai explicitement dédié au test.

## Préparer le tenant

1. Créer un site SharePoint `DLP-Pilot` et utiliser le OneDrive de `pilote-a`.
2. Créer une boîte Exchange de test et un canal Teams privé de test.
3. Dans Microsoft Purview, attribuer le rôle **Information Protection Admin**
   au compte `dlp-admin`.
4. Créer quatre étiquettes de sensibilité : Public, Interne, Confidentiel et
   Hautement confidentiel. Les correspondances doivent être validées par le
   RSSI/DPO avant toute publication.

## Scénario Purview DLP conseillé

Créer une politique `COMAR-DLP-POC` limitée au départ à `pilote-a` et aux
emplacements Exchange, SharePoint, OneDrive et Teams du lab.

| Règle | Condition de test | Action initiale |
| --- | --- | --- |
| C2 | Information interne vers externe | Journaliser / notifier |
| C3 | Données personnelles ou bancaires vers externe | Simulation avec notification |
| C4 | Données médicales ou stratégiques | Simulation, alerte haute |

Ne passer au blocage qu'après examen des faux positifs et faux négatifs. La
simulation Purview n'applique pas les actions configurées ; elle fournit les
résultats et alertes nécessaires pour les ajuster.

## Jeux de tests à exécuter

1. Envoyer un document C1 depuis `pilote-a` vers une adresse externe : aucun
   blocage attendu.
2. Envoyer un fichier contenant une CIN ou un IBAN fictif : alerte C3 attendue.
3. Charger un certificat médical fictif dans SharePoint/OneDrive : alerte C4
   attendue.
4. Tester l'envoi Teams et Exchange, puis vérifier les résultats dans Purview
   DLP > Policies > View simulation et dans Activity explorer.
5. Consigner pour chaque test : date, fichier, emplacement, résultat attendu,
   résultat observé, faux positif/faux négatif et décision de réglage.

## Connecteur Graph du POC

Le projet reste en simulation par défaut. Pour un pilote Graph restreint :

1. Copier `.env.example` en `.env` et renseigner uniquement les identifiants du
   tenant de lab et `GRAPH_TARGET_USER` du compte pilote.
2. Dans Entra ID, enregistrer une application dédiée au lab.
3. Accorder le minimum de permissions nécessaire ; pour SharePoint préférer
   `Sites.Selected` à `Files.Read.All`. N'ajouter `Mail.Send` que pour le
   bouton d'alerte.
4. Garder `microsoft365.enabled: false` tant que le RSSI/DPO n'a pas autorisé
   le test. Ce paramètre empêche tout appel Graph accidentel.

Le connecteur Graph lit et notifie ; il ne crée ni ne modifie de politique
Purview. Les politiques restent à configurer et valider dans le portail Purview.
