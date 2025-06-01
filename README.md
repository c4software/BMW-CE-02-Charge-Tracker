# BMW CE-02 Charge Tracker pour Home Assistant

Ce composant personnalisé pour Home Assistant vous permet de simuler et de suivre la charge de votre scooter électrique BMW CE-02. Il ne nécessite pas de connexion directe au véhicule ni de prise connectée mesurant la puissance ; la charge est déclenchée manuellement via un interrupteur dans Home Assistant.

## Fonctionnalités

* **Suivi du Niveau de Charge (SoC) :** Un capteur affiche le pourcentage de batterie estimé de votre BMW CE-02.
* **Simulation de Charge Manuelle :** Un interrupteur (`switch`) vous permet de démarrer et d'arrêter manuellement la simulation de charge.
* **Simulation de Charge à Deux Phases :**
  * Charge plus rapide de 0% à 80%.
  * Charge plus lente de 80% à 100% pour refléter un comportement de charge typique.
* **Estimations de Temps de Charge :**
  * Durée estimée pour atteindre 80% et 100%.
  * Heure estimée à laquelle 80% et 100% seront atteints.
* **Persistance de l'État :** Le niveau de charge et l'état de la session de charge (si elle était en cours) sont conservés après un redémarrage de Home Assistant.
* **Service de Réglage Manuel du SoC :** Permet d'ajuster le SoC actuel si l'estimation dévie.
* **Configuration via l'Interface Utilisateur.**

## Caractéristiques de Charge Simulées (par défaut)

Le composant utilise les valeurs suivantes, basées sur les informations typiques d'un BMW CE-02 :

* **Capacité Utile de la Batterie :** 3.92 kWh
* **Seuil de Changement de Phase de Charge :** 80% SoC
* **Puissance de Charge (Phase 1 : 0-80%) :** 0.9 kW
* **Puissance de Charge (Phase 2 : 80-100%) :** 0.517 kW (calculée pour un temps de charge total d'environ 5h)

## Installation

1. **Copier les Fichiers :**
    * Clonez ou téléchargez ce dépôt dans le dossier `custom_components` de votre configuration Home Assistant.
    * La structure devrait ressembler à : `<répertoire_config_ha>/custom_components/bmw_ce02_charge_tracker/`.

2. **Redémarrer Home Assistant :**
    * Redémarrez votre instance Home Assistant pour qu'il puisse détecter le nouveau composant.
    * Allez dans `Paramètres > Système > Redémarrer` (dans les versions récentes) ou utilisez les `Outils de développement > YAML > Redémarrer le serveur`.

## Configuration

Une fois Home Assistant redémarré :

1. Allez dans `Paramètres > Appareils et services`.
2. Cliquez sur le bouton `+ AJOUTER UNE INTÉGRATION` en bas à droite.
3. Recherchez "BMW CE-02 Charge Tracker" et sélectionnez-le.
4. Suivez les instructions à l'écran :
    * **Nom de l'appareil :** Choisissez un nom pour votre appareil (ex: "BMW CE-02", "Moto Cédric"). Ce nom sera utilisé pour préfixer les entités.

## Entités Fournies

Une fois configuré, le composant créera les entités suivantes (où `[Nom de l'appareil]` est le nom que vous avez configuré) :

* **Capteur de SoC :** `sensor.[nom_de_l_appareil]_estimated_soc`
  * Affiche le pourcentage de batterie estimé.
  * **Attributs clés :**
    * `is_charging`: `true` ou `false`.
    * `soc_at_charge_start`: SoC au début de la session de charge actuelle.
    * `charge_start_time`: Heure de début de la session de charge actuelle.
    * `duration_to_80_pct_hours`: Durée (en heures) pour atteindre 80%.
    * `time_at_80_pct`: Heure estimée (timestamp ISO) à laquelle 80% sera atteint.
    * `duration_to_100_pct_hours`: Durée (en heures) pour atteindre 100%.
    * `time_at_100_pct`: Heure estimée (timestamp ISO) à laquelle 100% sera atteint.
    * `current_charge_power_kw`: Puissance de charge simulée actuellement utilisée.
    * Et d'autres attributs relatifs à la persistance et aux paramètres de charge.

* **Interrupteur de Charge :** `switch.[nom_de_l_appareil]_charging_toggle`
  * Permet de démarrer (`on`) ou d'arrêter (`off`) manuellement la simulation de charge.

* **Capteur Binaire d'État de Charge :** `binary_sensor.[nom_de_l_appareil]_charging_status`
  * Indique si la simulation de charge est active (`on`) ou non (`off`).
  * `device_class` est réglé sur `battery_charging`.

## Services Fournis

* **`bmw_ce02_charge_tracker.set_current_soc`**
  * Permet de définir manuellement le niveau de charge actuel du capteur `sensor.[nom_de_l_appareil]_estimated_soc`.
  * **Paramètres :**
    * `entity_id`: L'ID de votre capteur SoC (ex: `sensor.bmw_ce_02_estimated_soc`).
    * `soc`: La valeur du SoC à définir (entre 0 et 100).
  * **Exemple d'utilisation (Outils de développement > Services) :**
        ```yaml
        service: bmw_ce02_charge_tracker.set_current_soc
        data:
          soc: 65
        target:
          entity_id: sensor.bmw_ce_02_estimated_soc 
        # Remplacez par l'ID de votre entité
        ```

## Utilisation

1. **Réglage Initial du SoC :** Après l'installation, il est important de régler le SoC initial de votre moto. Utilisez le service `bmw_ce02_charge_tracker.set_current_soc` (via les Outils de développement ou un script) pour que le capteur `sensor.[nom_de_l_appareil]_estimated_soc` reflète la réalité.

2. **Démarrer la Charge :**
    * Activez l'interrupteur `switch.[nom_de_l_appareil]_charging_toggle`.
    * Le capteur SoC commencera à augmenter en simulant la charge.

3. **Arrêter la Charge :**
    * Désactivez l'interrupteur `switch.[nom_de_l_appareil]_charging_toggle`.
    * Le capteur SoC arrêtera d'augmenter et conservera sa valeur actuelle.

4. **Consultation des Estimations :** Les attributs du capteur SoC vous donneront des indications sur les temps de charge restants.

## Limitations

* **Simulation Uniquement :** Ce composant fournit une *simulation* basée sur des paramètres fixes. Il ne lit aucune donnée réelle du véhicule.
* **Précision :** L'exactitude de la simulation dépend de la justesse du SoC initial que vous entrez manuellement et de la correspondance entre les paramètres de charge simulés et ceux de votre chargeur/véhicule réel.
* **Courbe de Charge Simplifiée :** La courbe de charge est une approximation à deux étapes. La charge réelle peut varier de manière plus complexe.