# BMW CE-02 Charge Tracker pour Home Assistant

Ce composant personnalisé pour Home Assistant vous permet de simuler et de suivre la charge de votre scooter électrique BMW CE-02. Il ne nécessite pas de connexion directe au véhicule ; la charge est déclenchée manuellement via un interrupteur dans Home Assistant.

## Fonctionnalités

* **Gestion du Niveau de Charge (SoC) :** Une entité "Nombre" (`number`) affiche le pourcentage de batterie estimé et permet de le régler manuellement (via un curseur ou un champ de saisie).
* **Simulation de Charge Manuelle :** Un interrupteur (`switch`) vous permet de démarrer et d'arrêter manuellement la simulation de charge.
* **Simulation de Charge à Deux Phases :**
  * Charge plus rapide (0.9 kW) de 0% à 80%.
  * Charge plus lente (0.517 kW) de 80% à 100%.
* **Capteurs de Durée et d'Énergie :**
  * Temps de charge écoulé pour la session en cours.
  * Temps restant estimé pour atteindre 80% (format HH:mm ou statut).
  * Temps restant estimé pour atteindre 100% (format HH:mm ou statut).
  * Énergie totale consommée (en kWh) pour le tableau de bord Énergie de Home Assistant.
* **Estimations d'Heure d'Atteinte :** Des attributs sur l'entité SoC indiquent l'heure estimée (timestamp ISO) à laquelle 80% et 100% seront atteints.
* **Persistance de l'État :** Le niveau de charge et l'état de la session de charge (si elle était en cours, y compris l'énergie consommée) sont conservés après un redémarrage de Home Assistant.
* **Configuration via l'Interface Utilisateur.**

## Caractéristiques de Charge Simulées (par défaut)

Le composant utilise les valeurs suivantes :

* **Capacité Utile de la Batterie :** 3.92 kWh
* **Seuil de Changement de Phase de Charge :** 80% SoC
* **Puissance de Charge (Phase 1 : 0-80%) :** 0.9 kW
* **Puissance de Charge (Phase 2 : 80-100%) :** 0.517 kW

## Installation

1. **Clonage du Dépôt :**
   * Clonez le dépôt GitHub dans votre répertoire `custom_components` de Home Assistant.

1. **Copier les Fichiers (alternative) :**
    * Assurez-vous d'avoir un dossier nommé `bmw_ce02_charge_tracker` (tout en minuscules avec underscores) dans votre répertoire `custom_components`.
    * Copiez tous les fichiers du composant (`__init__.py`, `sensor.py`, `number.py`, `switch.py`, `binary_sensor.py`, `const.py`, `config_flow.py`, `manifest.json`) dans ce dossier `custom_components/bmw_ce02_charge_tracker/`.

2. **Redémarrer Home Assistant :**
    * Allez dans `Paramètres > Système` et cliquez sur `REDÉMARRER` (en haut à droite).

## Configuration

Une fois Home Assistant redémarré :

1. Allez dans `Paramètres > Appareils et services`.
2. Cliquez sur le bouton `+ AJOUTER UNE INTÉGRATION` en bas à droite.
3. Recherchez "BMW CE-02 Charge Tracker" et sélectionnez-le.
4. Suivez les instructions à l'écran :
    * **Nom de l'appareil :** Choisissez un nom pour votre appareil (ex: "BMW CE-02", "Moto Cédric"). Ce nom sera utilisé pour les entités.

## Entités Fournies

Une fois configuré, le composant créera les entités suivantes (où `[nom_slug]` est une version simplifiée du nom de l'appareil que vous avez configuré, par exemple `bmw_ce_02` pour "BMW CE-02") :

* **Entité Nombre pour le SoC :** `number.[nom_slug]_soc` (par exemple, `number.bmw_ce_02_soc`)
  * Affiche le pourcentage de batterie estimé et permet de le régler.
  * **Attributs clés importants :**
    * `is_charging`: `true` ou `false`.
    * `soc_at_charge_start`: SoC au début de la session de charge.
    * `charge_start_time`: Heure de début de la session de charge (timestamp ISO).
    * `time_at_80_pct`: Heure estimée (timestamp ISO) à laquelle 80% sera atteint.
    * `time_at_100_pct`: Heure estimée (timestamp ISO) à laquelle 100% sera atteint.
    * `current_charge_power_kw`: Puissance de charge simulée actuellement utilisée (0.9, 0.517 ou 0 kW).
    * Attributs de persistance (ex: `persisted_is_charging_flag`).

* **Capteur de Temps de Charge Écoulé :** `sensor.[nom_slug]_temps_de_charge_ecoule`
  * Affiche le temps écoulé depuis le début de la session de charge actuelle.
  * Unité : secondes (Home Assistant l'affiche de manière conviviale, ex: "1 h 30 min").
  * `device_class: duration`.

* **Capteur de Temps Restant jusqu'à 80% :** `sensor.[nom_slug]_temps_restant_jusqu_a_80`
  * Affiche le temps restant estimé pour atteindre 80% SoC.
  * État : Format "HH:mm" (ex: "01:30") ou un statut ("Atteint", "Indisponible").

* **Capteur de Temps Restant jusqu'à 100% :** `sensor.[nom_slug]_temps_restant_jusqu_a_100`
  * Affiche le temps restant estimé pour atteindre 100% SoC.
  * État : Format "HH:mm" (ex: "02:45") ou un statut ("Pleine", "Indisponible").

* **Capteur d'Énergie Consommée :** `sensor.[nom_slug]_energie_consommee`
  * Affiche l'énergie totale consommée simulée par la charge.
  * Unité : kWh.
  * `device_class: energy`, `state_class: total_increasing` (pour le tableau de bord Énergie).

* **Interrupteur de Charge :** `switch.[nom_slug]_charging_toggle`
  * Permet de démarrer (`on`) ou d'arrêter (`off`) manuellement la simulation de charge.

* **Capteur Binaire d'État de Charge :** `binary_sensor.[nom_slug]_charging_status`
  * Indique si la simulation de charge est active (`on`) ou non (`off`).
  * `device_class: battery_charging`.

*(Note : Les `entity_id` exacts peuvent varier légèrement en fonction de la manière dont Home Assistant "slugifie" le nom de l'appareil. Vous les trouverez dans Outils de développement > États).*

## Services Fournis

Pour ajuster manuellement le SoC, utilisez l'entité `number` directement via l'interface utilisateur OU via le service standard `number.set_value` :

* **Service :** `number.set_value`
  * **Cible (`target`) :**
    * `entity_id`: L'ID de votre entité Nombre SoC (ex: `number.bmw_ce_02_soc`).
  * **Données (`data`) :**
    * `value`: La valeur du SoC à définir (nombre entre 0 et 100).
  * **Exemple d'utilisation (Outils de développement > Services) :**

        ```yaml
        service: number.set_value
        target:
          entity_id: number.bmw_ce_02_soc # Remplacez par l'ID réel de votre entité
        data:
          value: 65
        ```

## Utilisation

1. **Réglage Initial du SoC :** Après l'installation, réglez le SoC initial de votre moto en modifiant la valeur de l'entité `number.[nom_slug]_soc` via l'interface (curseur/champ) ou en utilisant le service `number.set_value`.

2. **Démarrer la Charge :** Activez l'interrupteur `switch.[nom_slug]_charging_toggle`. L'entité SoC et les capteurs de durée/énergie commenceront à se mettre à jour.

3. **Arrêter la Charge :** Désactivez l'interrupteur `switch.[nom_slug]_charging_toggle`.

4. **Tableau de Bord Énergie :** Vous pouvez ajouter le capteur `sensor.[nom_slug]_energie_consommee` à votre tableau de bord Énergie pour suivre la consommation simulée.

5. **Consultation des Estimations :**
    * Les temps restants (format HH:mm) sont disponibles via les capteurs de durée dédiés.
    * Les heures d'atteinte exactes (timestamp) sont des attributs de l'entité `number.[nom_slug]_soc`.

## Limitations

* **Simulation Uniquement :** Ce composant fournit une *simulation*. Il ne lit aucune donnée réelle du véhicule.
* **Précision :** L'exactitude dépend du SoC initial entré manuellement.
* **Courbe de Charge Simplifiée :** La charge est une approximation à deux étapes.