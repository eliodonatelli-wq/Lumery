# Lumerys · Palette Studio Native — 0.10.0.dev15

Versione di sviluppo isolata. Il nuovo nodo **Palette Studio** è un modulo della
catena Lumerys. Il vecchio nodo **Nebula Palette** non è più disponibile per
nuovi inserimenti; resta caricabile nei progetti salvati per compatibilità.
La build è installata nella cartella dedicata `lumerys_palette_native_dev`;
i plugin AstroSuite standalone restano invariati.

## Avvio

Chiudere il pannello Lumerys, scegliere **Reload Scripts** in SASpro e aprire
**Lumerys · Palette Native DEV**. Aggiungere **Palette Studio** e collegare
INPUT → Palette Studio → OUTPUT. Confermare lo stato dell'immagine in INPUT.
Il bypass è disponibile sul nodo e nel pannello. Reset all ripristina i default.
Il risultato viene aperto con il Render comune o salvato con Export FITS comune.
Per rimuovere questa DEV eliminare soltanto la cartella `lumerys_palette_native_dev`
dagli script e ricaricare gli script. Il rollback della build precedente si trova
nell'archivio di backup incluso nella cartella reports.

## Flusso di partenza suggerito

Quando la catena è vuota, il pannello **Suggested starting workflow** offre tre
tracce modificabili: OSC/RGB (Nebula Colors & Tone → Adaptive GHS → Curves),
narrowband classico (Palette Studio → Adaptive GHS → Curves) e Foraxx
(Adaptive GHS → Palette Studio Foraxx HOO → Curves). Cliccare una proposta monta
subito tutti i nodi reali, nell'ordine indicato, e collega INPUT a OUTPUT. Le
impostazioni iniziali restano modificabili. La proposta non avvia render o export.
Confermare prima lo stato dei dati in INPUT;
per Foraxx verificare la normalizzazione 0–1 dei canali usati. Per narrowband
mono fornire i FITS registrati e confermarne l'allineamento. Compressor,
Equalizer, Parametric EQ e Filament restano moduli facoltativi da inserire quando
servono. Freeze può fissare un passaggio intermedio.

## Palette incluse

Combinazioni lineari: HOO (Hα, OIII, OIII), SHO (SII, Hα, OIII), HSO, HOS, SOH, OSH e OHS. I codici indicano i gas assegnati a R/G/B. HOO riusa OIII su verde e blu; le altre permutazioni assegnano una volta ciascun gas. La matrice personalizzata resta disponibile per mappature diverse.

Foraxx HOO e Foraxx SHO usano le formule dinamiche PIP (Foraxx, Ludo / The Coldest Nights). Foraxx richiede ingresso dichiarato non-lineare. La Palette Studio misura i canali effettivamente usati dopo curve e guadagni. Se il massimo supera 1, applica un solo divisore comune a tutti quei canali prima della formula: preserva i rapporti e non clippa i dati. I valori negativi restano un errore esplicito e sono accompagnati dagli intervalli per canale; per correggerli si possono regolare curve, guadagni o normalizzazione fissa. La SII sintetica Foraxx è positiva e limitata a [0,1]. La selezione Foraxx SHO attiva automaticamente la sintesi. Nessuno stretch automatico dell'immagine sorgente.

Credito e formula originale: [The Coldest Nights — Dynamic Narrowband Combinations with PixelMath](https://thecoldestnights.com/2020/06/pixinsight-dynamic-narrowband-combinations-with-pixelmath/). PIP `t=(H×O)^(1−H×O)`, verde `t×H+(1−t)×O`; Foraxx SHO miscela H/S con `u=O^(1−O)`.

## Segnali e composizione

Default: Hα = R, OIII = (G+B)/2; SII assente. Sono stime numeriche, non una
separazione fisica garantita, soprattutto per RGB a banda larga e dati stirati.
La matrice di estrazione espone i coefficienti; nessuna calibrazione sensore è
nascosta. I segnali FITS devono essere mono, finiti, della stessa dimensione
dell'ingresso e già registrati allo stesso campo. La conferma manuale di
allineamento è obbligatoria: non viene eseguita astrometria o registrazione.
Si usa Astropy, già presente per l'OUTPUT FITS. Nessun secondo importatore host,
stretch o esportatore viene introdotto.

Ordine: acquisizione → normalizzazione opzionale → sintesi SII opzionale →
curve gas → guadagni → matrice RGB → curve RGB. Con protezione attiva, curve gas
e guadagni operano sul residuo dal fondo specificato, come indicato sotto.

Ordine gas: (Hα,OIII,SII). HOO = (Hα,OIII,OIII). SHO = (SII,Hα,OIII).
La matrice personalizzata ha righe R,G,B e colonne Hα,OIII,SII e sostituisce
la matrice della palette. Se la matrice richiede SII e manca il segnale,
l'elaborazione si ferma con un errore esplicito.

Normalizzazione disattivata per default. Quando attiva:
`gas = (gas - offset) / scale`, con un solo offset e divisore manuali.
Il sistema comune di INPUT mantiene le sue convenzioni esistenti per interi.

SII artificiale: `S = gain * (H - subtraction*O)`. Softness=0 conserva il segno.
Con softness>0, il residuo x diventa `(x + hypot(x,softness))/2` prima del gain.
La sintesi sostituisce l'eventuale SII in ingresso ed è sempre identificata come
artificiale. Non costituisce una misura di zolfo. I nomi dei componenti esportati
identificano separatamente stime RGB e SII sintetico.

Le curve monotone usano il componente numerico comune PCHIP, con extrapolazione
lineare delle tangenti oltre il dominio. Non c'è clipping dei campioni, né
normalizzazione ai massimi, riduzione verde, bilanciamento automatico o stretch.
Valori negativi e superiori a 1 restano nei risultati numerici. La visualizzazione
può saturarli senza modificare l'immagine esportata.

## Neutralizzazione del cielo

Disattivata per default. Attivarla, premere **Seleziona rettangolo del fondo cielo**
e trascinare un rettangolo su una zona vuota dell’immagine nel pannello di anteprima
comune. La selezione viene fatta sull’ingresso del nodo, salvata come coordinate
relative all’immagine e applicata ai pixel nativi. Si può rimuovere in ogni momento.

La mediana RGB del rettangolo viene portata a un livello neutro (media dei tre
canali) con una traslazione cromatica costante, regolata dall’intensità. La stessa
traslazione si applica a tutti i pixel: conserva le differenze fra pixel e non
classifica né cancella la nebulosità debole. Non corregge gradienti spaziali;
scegliere una zona vuota e rappresentativa del fondo. Il campione descrive il
fondo al punto selezionato, mentre la traslazione uniforme presume un fondo
abbastanza costante. Valori negativi restano ammessi, senza clipping.

La maschera diagnostica mostra in bianco l’area a cui si applica la correzione;
la vista usa il preview comune e non entra nell’output finale.

## Risoluzioni, cache e dati

Il nodo riceve l'ingresso nativo, esegue il motore una volta a piena risoluzione,
e riduce il risultato con il ricampionamento comune per 1/2,1/4,1/8. Per ottenere
l'ingresso nativo viene eseguito il prefisso della catena a Full, rispettando Freeze.
Si evita il cambio di colori dovuto a statistiche o non linearità sui proxy.
Il primo aggiornamento e i cambiamenti a monte possono quindi costare più tempo
rispetto ai vecchi proxy; la cache conserva il risultato nativo. Un singolo frame
nativo può superare il budget cache, come il checkpoint Freeze.

La coerenza dimostrata riguarda l'uscita di questo nodo: altri moduli a valle
possono avere proprie approssimazioni alle diverse risoluzioni.

I FITS esterni sono verificati tramite SHA-256, anche nelle chiavi cache.
Il progetto salva percorsi e impronte; se i file cambiano il caricamento viene
rifiutato. I FITS non sono incorporati nel progetto: conservarli insieme ai dati.
Non viene modificato alcun file sorgente.

## Validazione e limiti

Vedere reports/final_tests.log, real_verification.json e integrity.json.
Test automatici: motore numerico, matrici, curve, sintesi, dati firmati, maschera,
risoluzioni, bypass, reset, serializzazione, input FITS, render con host simulato,
maschera solo display ed esportazione tramite servizi comuni.

Prova reale: ingresso astronomico archiviato 2021×2922 pixel, HOO completo;
anteprime 1/2,1/4,1/8 identiche al Full ridotto. Il confronto PNG contiene un
ritaglio centrale: originale | HOO | SHO con SII artificiale, scala display uguale.
La qualità della protezione del fondo su quel campo non è certificata.

Test UI eseguiti offscreen sul Mac con Qt del runtime di sviluppo.
NON verificati: sessione interattiva SASpro, secondo Mac, Windows.
Questa DEV non è una release di produzione.

## File e riproduzione

`AstroChain_Prototype.py` e `_astrochain_lib.zip` devono restare insieme;
lo ZIP interno non va estratto. L'archivio esterno contiene anche src/, tests/,
rapporti e questo documento. Dipendenze: Python 3.12, NumPy, SciPy, PyQt6,
Astropy (solo ingressi/esportazioni FITS). Nessuna nuova libreria richiesta a SASpro.

Per i test dedicati in un ambiente con tali dipendenze:
`PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests`
La suite completa locale include anche confronti con i moduli originali conservati
nel workspace; il rapporto ne registra l'esecuzione.
