# Architettura implementata e fasi

1. Analisi: versione 0.9.7.dev7 installata confrontata con tutti gli 88 sorgenti
   Python del development precedente; corrispondenza completa prima del lavoro.
   La proposta è stata presentata e approvata dall'utente.
2. Motore: palette_native.py, indipendente da Qt e dal vendor Nebula. I primi
   16 test numerici sono passati prima dell'integrazione.
3. Test indipendenti: matrici note, curve, segnali firmati, maschera continua,
   sintesi e ripetibilità. Successivamente ampliati con casi ulteriori.
4. Integrazione: tipo palette_native. Sono estesi soltanto i punti espliciti di
   registrazione, parsing/salvataggio, dispatch, diagnostica ed esportazione dei
   canali. Non si modifica il comportamento dei precedenti tipi di modulo.
5. Pannello: inspector Qt secondo le convenzioni comuni, curve riusate,
   anteprima condivisa, nessun nuovo stretch/output. Render/Export con host
   simulato e prova di maschera che non modifica i dati finali. Prova reale
   numerica ed esame del confronto renderizzato. Verifica interattiva SASpro,
   giudizio astronomico su più campi e piattaforme ulteriori ancora da fare.

## Scelte tecniche rispetto alla proposta

Per eliminare l'errore non lineare elaborazione/dowsampling, la prima DEV esegue
l'intero nodo sul dato nativo e riduce il risultato, non soltanto le statistiche.
La logica è nel dispatch del nuovo nodo. Gli altri motori mantengono i loro proxy.
Il riferimento nativo del prefisso passa dallo stesso compute_serial; Freeze
resta il checkpoint comune. Non si creano scheduler, code o pool aggiuntivi.

I FITS Ha/OIII/SII sono side input dichiarati nel nuovo nodo: non vengono
trasformate le porte seriali in un nuovo grafo multiplo. Il supporto di immagini
mono in FITS usa Astropy, già dipendenza dell'output. Il dato principale e il
suo campo restano quelli della catena; i canali sono dichiarati già registrati.
Non è implementato un adattamento da altri documenti aperti perché l'API host
esaminata espone soltanto get_image/active_document per la selezione corrente.

Il nuovo motore non importa gas_palette, nebula_processing, foraxx o vendor
Nebula. L'applicazione completa continua a caricare i vecchi moduli per
compatibilità dei progetti. Non ne deriva una dipendenza numerica del nuovo nodo.

I parametri del fondo sono manuali ed espliciti. Non è stata riutilizzata la
vecchia neutralizzazione per non introdurne il motore o le statistiche implicite.
L'identificazione automatica affidabile del fondo non viene dichiarata risolta.
