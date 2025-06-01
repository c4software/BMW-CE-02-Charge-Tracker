# BMW CE-02 Charge Tracker

Cette intégration simule et suit la charge de votre scooter électrique BMW CE-02 dans Home Assistant.

## Caractéristiques

- Simulation de charge manuelle via un interrupteur.
- Gestion du niveau de charge (SoC) avec une entité nombre.
- Simulation de charge à deux phases (rapide jusqu'à 80%, plus lente ensuite).
- Capteurs pour le temps de charge écoulé et le temps restant estimé (pour 80% et 100% SoC).
- Capteur d'énergie consommée, compatible avec le tableau de bord Énergie.
- Estimations d'heure d'atteinte pour 80% et 100% SoC (en tant qu'attributs).
- Persistance de l'état de charge et du SoC après redémarrage de Home Assistant.
- Configuration simple via l'interface utilisateur de Home Assistant.
- **Attention :** Ce composant est une *simulation* et ne lit pas les données réelles du véhicule.

## Installation

1. Ajoutez l'intégration via HACS (recherchez "BMW CE-02 Charge Tracker").
2. Redémarrez Home Assistant.
3. Allez dans `Paramètres > Appareils et services`, cliquez sur `+ AJOUTER UNE INTÉGRATION` et recherchez "BMW CE-02 Charge Tracker".
4. Suivez les instructions pour configurer le nom de l'appareil.
