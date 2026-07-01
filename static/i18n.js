/* NADO light-miner i18n. Classic (non-module) script loaded BEFORE miner.js so it can localize the
 * static DOM and expose window.t() for the module. Language defaults to the browser locale
 * (navigator.languages), overridable via the header picker (persisted in localStorage). English is the
 * fallback for any missing key, so a partial translation degrades gracefully. RTL langs flip <html dir>.
 *
 * Tag elements with data-i18n="key" (textContent), data-i18n-ph="key" (placeholder), or
 * data-i18n-title="key" (title). Add a language by adding its table + NAMES entry. */
(function () {
  "use strict";

  const T = {
    en: {
      "tab.wallet":"Wallet","tab.send":"Send","tab.receive":"Receive","tab.aliases":"Aliases","tab.stake":"Stake","tab.history":"History","tab.explore":"Explore","tab.settings":"Settings",
      "app.sub":"browser-only · no full node","conn.connecting":"connecting…",
      "onboard.title":"Get started","btn.genKey":"Generate new key","btn.importKey":"Import key","btn.import":"Import",
      "save.title":"⚠ Save your private key","save.ack":"I have saved my private key","save.continue":"Continue → store on this device",
      "wallet.title":"Wallet","lbl.address":"Address","lbl.free":"Free","lbl.bonded":"Bonded","lbl.total":"Total","lbl.registered":"Registered","lbl.present":"Present","lbl.fidelity":"Fidelity","wallet.reveal":"Reveal / export private key","btn.dlKey":"⤓ Download key file (JSON)",
      "mining.title":"Mining","btn.startMining":"Start mining","btn.stopMining":"Stop mining","mine.status":"Status","mine.epoch":"Current epoch","mine.eta":"Expected time to mine","mine.nextHb":"Next heartbeat","mine.idle":"Idle",
      "lanes.title":"Selection lanes","lanes.open":"Open lane","lanes.bonded":"Bonded lane","lanes.openWeight":"Open weight","lanes.bondedShares":"Bonded shares",
      "send.title":"Send","send.recipient":"Recipient address","send.amount":"Amount (NADO)","send.fee":"Network fee:","send.spendable":"Spendable balance:","btn.reviewSend":"Review & send",
      "receive.title":"Receive","receive.reqAmount":"Request amount (NADO) — optional","receive.payLink":"Payment link","receive.your":"Your address","btn.copy":"Copy","btn.share":"Share",
      "alias.title":"Aliases","alias.name":"Alias name","btn.register":"Register","btn.unregister":"Unregister","btn.transfer":"Transfer","alias.transferTo":"Transfer ownership to (ndo… address)","alias.your":"Your aliases:",
      "stake.title":"Stake — bond / unbond","stake.spendable":"Spendable","stake.bondAmount":"Bond amount (NADO)","stake.unbondAmount":"Unbond amount (NADO)","btn.bond":"Bond stake","btn.unbond":"Unbond stake","stake.autobond":"Auto-bond mining rewards","stake.noFee":"No network fee — unbonding is free.",
      "history.title":"History","btn.refresh":"Refresh",
      "explore.title":"Explore","btn.search":"Search","explore.network":"Network","explore.mining":"Mining","explore.recent":"Recent blocks",
      "settings.title":"Settings","settings.relay":"Relay node URL","btn.save":"Save","btn.selftest":"Run self-test","btn.forget":"Forget wallet"
    },
    cs: {
      "tab.wallet":"Peněženka","tab.send":"Odeslat","tab.receive":"Přijmout","tab.aliases":"Aliasy","tab.stake":"Staking","tab.history":"Historie","tab.explore":"Průzkumník","tab.settings":"Nastavení",
      "app.sub":"jen prohlížeč · bez plného uzlu","conn.connecting":"připojování…",
      "onboard.title":"Začít","btn.genKey":"Vytvořit nový klíč","btn.importKey":"Importovat klíč","btn.import":"Importovat",
      "save.title":"⚠ Uložte si soukromý klíč","save.ack":"Uložil/a jsem si soukromý klíč","save.continue":"Pokračovat → uložit do tohoto zařízení",
      "wallet.title":"Peněženka","lbl.address":"Adresa","lbl.free":"K dispozici","lbl.bonded":"Ve stakingu","lbl.total":"Celkem","lbl.registered":"Registrováno","lbl.present":"Přítomen","lbl.fidelity":"Věrnost","wallet.reveal":"Zobrazit / exportovat soukromý klíč","btn.dlKey":"⤓ Stáhnout soubor klíče (JSON)",
      "mining.title":"Těžba","btn.startMining":"Spustit těžbu","btn.stopMining":"Zastavit těžbu","mine.status":"Stav","mine.epoch":"Aktuální epocha","mine.eta":"Odhadovaný čas do vytěžení","mine.nextHb":"Další tep","mine.idle":"Nečinné",
      "lanes.title":"Výběrové dráhy","lanes.open":"Otevřená dráha","lanes.bonded":"Staking dráha","lanes.openWeight":"Otevřená váha","lanes.bondedShares":"Staking podíly",
      "send.title":"Odeslat","send.recipient":"Adresa příjemce","send.amount":"Částka (NADO)","send.fee":"Síťový poplatek:","send.spendable":"Dostupný zůstatek:","btn.reviewSend":"Zkontrolovat a odeslat",
      "receive.title":"Přijmout","receive.reqAmount":"Požadovaná částka (NADO) — volitelné","receive.payLink":"Platební odkaz","receive.your":"Vaše adresa","btn.copy":"Kopírovat","btn.share":"Sdílet",
      "alias.title":"Aliasy","alias.name":"Název aliasu","btn.register":"Registrovat","btn.unregister":"Zrušit","btn.transfer":"Převést","alias.transferTo":"Převést vlastnictví na (adresa ndo…)","alias.your":"Vaše aliasy:",
      "stake.title":"Staking — vložit / vybrat","stake.spendable":"K dispozici","stake.bondAmount":"Částka k vložení (NADO)","stake.unbondAmount":"Částka k výběru (NADO)","btn.bond":"Vložit do stakingu","btn.unbond":"Vybrat ze stakingu","stake.autobond":"Automaticky stakovat odměny z těžby","stake.noFee":"Bez poplatku — výběr je zdarma.",
      "history.title":"Historie","btn.refresh":"Obnovit",
      "explore.title":"Průzkumník","btn.search":"Hledat","explore.network":"Síť","explore.mining":"Těžba","explore.recent":"Nedávné bloky",
      "settings.title":"Nastavení","settings.relay":"URL relay uzlu","btn.save":"Uložit","btn.selftest":"Spustit autotest","btn.forget":"Zapomenout peněženku"
    },
    es: {
      "tab.wallet":"Cartera","tab.send":"Enviar","tab.receive":"Recibir","tab.aliases":"Alias","tab.stake":"Staking","tab.history":"Historial","tab.explore":"Explorar","tab.settings":"Ajustes",
      "app.sub":"solo navegador · sin nodo completo","conn.connecting":"conectando…",
      "onboard.title":"Comenzar","btn.genKey":"Generar clave nueva","btn.importKey":"Importar clave","btn.import":"Importar",
      "save.title":"⚠ Guarda tu clave privada","save.ack":"He guardado mi clave privada","save.continue":"Continuar → guardar en este dispositivo",
      "wallet.title":"Cartera","lbl.address":"Dirección","lbl.free":"Libre","lbl.bonded":"En stake","lbl.total":"Total","lbl.registered":"Registrado","lbl.present":"Presente","lbl.fidelity":"Fidelidad","wallet.reveal":"Mostrar / exportar clave privada","btn.dlKey":"⤓ Descargar archivo de clave (JSON)",
      "mining.title":"Minería","btn.startMining":"Empezar a minar","btn.stopMining":"Detener minería","mine.status":"Estado","mine.epoch":"Época actual","mine.eta":"Tiempo estimado para minar","mine.nextHb":"Próximo latido","mine.idle":"Inactivo",
      "lanes.title":"Carriles de selección","lanes.open":"Carril abierto","lanes.bonded":"Carril con stake","lanes.openWeight":"Peso abierto","lanes.bondedShares":"Participaciones en stake",
      "send.title":"Enviar","send.recipient":"Dirección del destinatario","send.amount":"Cantidad (NADO)","send.fee":"Comisión de red:","send.spendable":"Saldo disponible:","btn.reviewSend":"Revisar y enviar",
      "receive.title":"Recibir","receive.reqAmount":"Cantidad solicitada (NADO) — opcional","receive.payLink":"Enlace de pago","receive.your":"Tu dirección","btn.copy":"Copiar","btn.share":"Compartir",
      "alias.title":"Alias","alias.name":"Nombre de alias","btn.register":"Registrar","btn.unregister":"Cancelar","btn.transfer":"Transferir","alias.transferTo":"Transferir propiedad a (dirección ndo…)","alias.your":"Tus alias:",
      "stake.title":"Staking — bloquear / liberar","stake.spendable":"Disponible","stake.bondAmount":"Cantidad a bloquear (NADO)","stake.unbondAmount":"Cantidad a liberar (NADO)","btn.bond":"Bloquear stake","btn.unbond":"Liberar stake","stake.autobond":"Auto-stake de recompensas","stake.noFee":"Sin comisión — liberar es gratis.",
      "history.title":"Historial","btn.refresh":"Actualizar",
      "explore.title":"Explorar","btn.search":"Buscar","explore.network":"Red","explore.mining":"Minería","explore.recent":"Bloques recientes",
      "settings.title":"Ajustes","settings.relay":"URL del nodo relé","btn.save":"Guardar","btn.selftest":"Ejecutar autoprueba","btn.forget":"Olvidar cartera"
    },
    pt: {
      "tab.wallet":"Carteira","tab.send":"Enviar","tab.receive":"Receber","tab.aliases":"Apelidos","tab.stake":"Stake","tab.history":"Histórico","tab.explore":"Explorar","tab.settings":"Definições",
      "app.sub":"só navegador · sem nó completo","conn.connecting":"a ligar…",
      "onboard.title":"Começar","btn.genKey":"Gerar nova chave","btn.importKey":"Importar chave","btn.import":"Importar",
      "save.title":"⚠ Guarde a sua chave privada","save.ack":"Guardei a minha chave privada","save.continue":"Continuar → guardar neste dispositivo",
      "wallet.title":"Carteira","lbl.address":"Endereço","lbl.free":"Livre","lbl.bonded":"Em stake","lbl.total":"Total","lbl.registered":"Registado","lbl.present":"Presente","lbl.fidelity":"Fidelidade","wallet.reveal":"Mostrar / exportar chave privada","btn.dlKey":"⤓ Descarregar ficheiro de chave (JSON)",
      "mining.title":"Mineração","btn.startMining":"Iniciar mineração","btn.stopMining":"Parar mineração","mine.status":"Estado","mine.epoch":"Época atual","mine.eta":"Tempo estimado para minerar","mine.nextHb":"Próximo heartbeat","mine.idle":"Inativo",
      "lanes.title":"Faixas de seleção","lanes.open":"Faixa aberta","lanes.bonded":"Faixa com stake","lanes.openWeight":"Peso aberto","lanes.bondedShares":"Cotas em stake",
      "send.title":"Enviar","send.recipient":"Endereço do destinatário","send.amount":"Quantia (NADO)","send.fee":"Taxa de rede:","send.spendable":"Saldo disponível:","btn.reviewSend":"Rever e enviar",
      "receive.title":"Receber","receive.reqAmount":"Quantia pedida (NADO) — opcional","receive.payLink":"Link de pagamento","receive.your":"O seu endereço","btn.copy":"Copiar","btn.share":"Partilhar",
      "alias.title":"Apelidos","alias.name":"Nome do apelido","btn.register":"Registar","btn.unregister":"Cancelar","btn.transfer":"Transferir","alias.transferTo":"Transferir posse para (endereço ndo…)","alias.your":"Os seus apelidos:",
      "stake.title":"Stake — bloquear / desbloquear","stake.spendable":"Disponível","stake.bondAmount":"Quantia a bloquear (NADO)","stake.unbondAmount":"Quantia a desbloquear (NADO)","btn.bond":"Bloquear stake","btn.unbond":"Desbloquear stake","stake.autobond":"Auto-stake das recompensas","stake.noFee":"Sem taxa — desbloquear é grátis.",
      "history.title":"Histórico","btn.refresh":"Atualizar",
      "explore.title":"Explorar","btn.search":"Pesquisar","explore.network":"Rede","explore.mining":"Mineração","explore.recent":"Blocos recentes",
      "settings.title":"Definições","settings.relay":"URL do nó relé","btn.save":"Guardar","btn.selftest":"Executar autoteste","btn.forget":"Esquecer carteira"
    },
    fr: {
      "tab.wallet":"Portefeuille","tab.send":"Envoyer","tab.receive":"Recevoir","tab.aliases":"Alias","tab.stake":"Staking","tab.history":"Historique","tab.explore":"Explorer","tab.settings":"Paramètres",
      "app.sub":"navigateur seul · sans nœud complet","conn.connecting":"connexion…",
      "onboard.title":"Commencer","btn.genKey":"Générer une nouvelle clé","btn.importKey":"Importer une clé","btn.import":"Importer",
      "save.title":"⚠ Sauvegardez votre clé privée","save.ack":"J'ai sauvegardé ma clé privée","save.continue":"Continuer → stocker sur cet appareil",
      "wallet.title":"Portefeuille","lbl.address":"Adresse","lbl.free":"Libre","lbl.bonded":"En stake","lbl.total":"Total","lbl.registered":"Enregistré","lbl.present":"Présent","lbl.fidelity":"Fidélité","wallet.reveal":"Afficher / exporter la clé privée","btn.dlKey":"⤓ Télécharger le fichier de clé (JSON)",
      "mining.title":"Minage","btn.startMining":"Démarrer le minage","btn.stopMining":"Arrêter le minage","mine.status":"Statut","mine.epoch":"Époque actuelle","mine.eta":"Temps estimé avant minage","mine.nextHb":"Prochain battement","mine.idle":"Inactif",
      "lanes.title":"Voies de sélection","lanes.open":"Voie ouverte","lanes.bonded":"Voie stakée","lanes.openWeight":"Poids ouvert","lanes.bondedShares":"Parts stakées",
      "send.title":"Envoyer","send.recipient":"Adresse du destinataire","send.amount":"Montant (NADO)","send.fee":"Frais réseau :","send.spendable":"Solde disponible :","btn.reviewSend":"Vérifier et envoyer",
      "receive.title":"Recevoir","receive.reqAmount":"Montant demandé (NADO) — facultatif","receive.payLink":"Lien de paiement","receive.your":"Votre adresse","btn.copy":"Copier","btn.share":"Partager",
      "alias.title":"Alias","alias.name":"Nom d'alias","btn.register":"Enregistrer","btn.unregister":"Supprimer","btn.transfer":"Transférer","alias.transferTo":"Transférer la propriété à (adresse ndo…)","alias.your":"Vos alias :",
      "stake.title":"Staking — bloquer / débloquer","stake.spendable":"Disponible","stake.bondAmount":"Montant à bloquer (NADO)","stake.unbondAmount":"Montant à débloquer (NADO)","btn.bond":"Bloquer le stake","btn.unbond":"Débloquer le stake","stake.autobond":"Auto-stake des récompenses","stake.noFee":"Aucun frais — le déblocage est gratuit.",
      "history.title":"Historique","btn.refresh":"Actualiser",
      "explore.title":"Explorer","btn.search":"Rechercher","explore.network":"Réseau","explore.mining":"Minage","explore.recent":"Blocs récents",
      "settings.title":"Paramètres","settings.relay":"URL du nœud relais","btn.save":"Enregistrer","btn.selftest":"Lancer l'autotest","btn.forget":"Oublier le portefeuille"
    },
    de: {
      "tab.wallet":"Wallet","tab.send":"Senden","tab.receive":"Empfangen","tab.aliases":"Aliase","tab.stake":"Staking","tab.history":"Verlauf","tab.explore":"Erkunden","tab.settings":"Einstellungen",
      "app.sub":"nur Browser · kein Full-Node","conn.connecting":"verbinde…",
      "onboard.title":"Loslegen","btn.genKey":"Neuen Schlüssel erzeugen","btn.importKey":"Schlüssel importieren","btn.import":"Importieren",
      "save.title":"⚠ Sichere deinen privaten Schlüssel","save.ack":"Ich habe meinen privaten Schlüssel gesichert","save.continue":"Weiter → auf diesem Gerät speichern",
      "wallet.title":"Wallet","lbl.address":"Adresse","lbl.free":"Frei","lbl.bonded":"Gebunden","lbl.total":"Gesamt","lbl.registered":"Registriert","lbl.present":"Anwesend","lbl.fidelity":"Treue","wallet.reveal":"Privaten Schlüssel anzeigen / exportieren","btn.dlKey":"⤓ Schlüsseldatei herunterladen (JSON)",
      "mining.title":"Mining","btn.startMining":"Mining starten","btn.stopMining":"Mining stoppen","mine.status":"Status","mine.epoch":"Aktuelle Epoche","mine.eta":"Geschätzte Zeit bis zum Mining","mine.nextHb":"Nächster Heartbeat","mine.idle":"Inaktiv",
      "lanes.title":"Auswahl-Spuren","lanes.open":"Offene Spur","lanes.bonded":"Gebundene Spur","lanes.openWeight":"Offenes Gewicht","lanes.bondedShares":"Gebundene Anteile",
      "send.title":"Senden","send.recipient":"Empfängeradresse","send.amount":"Betrag (NADO)","send.fee":"Netzwerkgebühr:","send.spendable":"Verfügbares Guthaben:","btn.reviewSend":"Prüfen & senden",
      "receive.title":"Empfangen","receive.reqAmount":"Angeforderter Betrag (NADO) — optional","receive.payLink":"Zahlungslink","receive.your":"Deine Adresse","btn.copy":"Kopieren","btn.share":"Teilen",
      "alias.title":"Aliase","alias.name":"Alias-Name","btn.register":"Registrieren","btn.unregister":"Freigeben","btn.transfer":"Übertragen","alias.transferTo":"Eigentum übertragen an (ndo…-Adresse)","alias.your":"Deine Aliase:",
      "stake.title":"Staking — binden / lösen","stake.spendable":"Verfügbar","stake.bondAmount":"Zu bindender Betrag (NADO)","stake.unbondAmount":"Zu lösender Betrag (NADO)","btn.bond":"Stake binden","btn.unbond":"Stake lösen","stake.autobond":"Mining-Belohnungen auto-binden","stake.noFee":"Keine Gebühr — Lösen ist kostenlos.",
      "history.title":"Verlauf","btn.refresh":"Aktualisieren",
      "explore.title":"Erkunden","btn.search":"Suchen","explore.network":"Netzwerk","explore.mining":"Mining","explore.recent":"Neueste Blöcke",
      "settings.title":"Einstellungen","settings.relay":"Relay-Node-URL","btn.save":"Speichern","btn.selftest":"Selbsttest ausführen","btn.forget":"Wallet vergessen"
    },
    it: {
      "tab.wallet":"Portafoglio","tab.send":"Invia","tab.receive":"Ricevi","tab.aliases":"Alias","tab.stake":"Staking","tab.history":"Cronologia","tab.explore":"Esplora","tab.settings":"Impostazioni",
      "app.sub":"solo browser · nessun nodo completo","conn.connecting":"connessione…",
      "onboard.title":"Inizia","btn.genKey":"Genera nuova chiave","btn.importKey":"Importa chiave","btn.import":"Importa",
      "save.title":"⚠ Salva la tua chiave privata","save.ack":"Ho salvato la mia chiave privata","save.continue":"Continua → salva su questo dispositivo",
      "wallet.title":"Portafoglio","lbl.address":"Indirizzo","lbl.free":"Libero","lbl.bonded":"In stake","lbl.total":"Totale","lbl.registered":"Registrato","lbl.present":"Presente","lbl.fidelity":"Fedeltà","wallet.reveal":"Mostra / esporta chiave privata","btn.dlKey":"⤓ Scarica file chiave (JSON)",
      "mining.title":"Mining","btn.startMining":"Avvia mining","btn.stopMining":"Ferma mining","mine.status":"Stato","mine.epoch":"Epoca attuale","mine.eta":"Tempo stimato per il mining","mine.nextHb":"Prossimo heartbeat","mine.idle":"Inattivo",
      "lanes.title":"Corsie di selezione","lanes.open":"Corsia aperta","lanes.bonded":"Corsia in stake","lanes.openWeight":"Peso aperto","lanes.bondedShares":"Quote in stake",
      "send.title":"Invia","send.recipient":"Indirizzo del destinatario","send.amount":"Importo (NADO)","send.fee":"Commissione di rete:","send.spendable":"Saldo disponibile:","btn.reviewSend":"Rivedi e invia",
      "receive.title":"Ricevi","receive.reqAmount":"Importo richiesto (NADO) — facoltativo","receive.payLink":"Link di pagamento","receive.your":"Il tuo indirizzo","btn.copy":"Copia","btn.share":"Condividi",
      "alias.title":"Alias","alias.name":"Nome alias","btn.register":"Registra","btn.unregister":"Rimuovi","btn.transfer":"Trasferisci","alias.transferTo":"Trasferisci proprietà a (indirizzo ndo…)","alias.your":"I tuoi alias:",
      "stake.title":"Staking — vincola / svincola","stake.spendable":"Disponibile","stake.bondAmount":"Importo da vincolare (NADO)","stake.unbondAmount":"Importo da svincolare (NADO)","btn.bond":"Vincola stake","btn.unbond":"Svincola stake","stake.autobond":"Auto-stake delle ricompense","stake.noFee":"Nessuna commissione — svincolare è gratis.",
      "history.title":"Cronologia","btn.refresh":"Aggiorna",
      "explore.title":"Esplora","btn.search":"Cerca","explore.network":"Rete","explore.mining":"Mining","explore.recent":"Blocchi recenti",
      "settings.title":"Impostazioni","settings.relay":"URL del nodo relay","btn.save":"Salva","btn.selftest":"Esegui autotest","btn.forget":"Dimentica portafoglio"
    },
    ru: {
      "tab.wallet":"Кошелёк","tab.send":"Отправить","tab.receive":"Получить","tab.aliases":"Псевдонимы","tab.stake":"Стейк","tab.history":"История","tab.explore":"Обзор","tab.settings":"Настройки",
      "app.sub":"только браузер · без полного узла","conn.connecting":"подключение…",
      "onboard.title":"Начать","btn.genKey":"Создать новый ключ","btn.importKey":"Импортировать ключ","btn.import":"Импорт",
      "save.title":"⚠ Сохраните приватный ключ","save.ack":"Я сохранил приватный ключ","save.continue":"Продолжить → сохранить на этом устройстве",
      "wallet.title":"Кошелёк","lbl.address":"Адрес","lbl.free":"Свободно","lbl.bonded":"В стейке","lbl.total":"Всего","lbl.registered":"Зарегистрирован","lbl.present":"Активен","lbl.fidelity":"Верность","wallet.reveal":"Показать / экспортировать приватный ключ","btn.dlKey":"⤓ Скачать файл ключа (JSON)",
      "mining.title":"Майнинг","btn.startMining":"Начать майнинг","btn.stopMining":"Остановить майнинг","mine.status":"Статус","mine.epoch":"Текущая эпоха","mine.eta":"Ожидаемое время до блока","mine.nextHb":"Следующий сигнал","mine.idle":"Ожидание",
      "lanes.title":"Полосы отбора","lanes.open":"Открытая полоса","lanes.bonded":"Полоса стейка","lanes.openWeight":"Открытый вес","lanes.bondedShares":"Доли стейка",
      "send.title":"Отправить","send.recipient":"Адрес получателя","send.amount":"Сумма (NADO)","send.fee":"Комиссия сети:","send.spendable":"Доступный баланс:","btn.reviewSend":"Проверить и отправить",
      "receive.title":"Получить","receive.reqAmount":"Запрашиваемая сумма (NADO) — необязательно","receive.payLink":"Ссылка на оплату","receive.your":"Ваш адрес","btn.copy":"Копировать","btn.share":"Поделиться",
      "alias.title":"Псевдонимы","alias.name":"Имя псевдонима","btn.register":"Зарегистрировать","btn.unregister":"Освободить","btn.transfer":"Передать","alias.transferTo":"Передать владение на (адрес ndo…)","alias.your":"Ваши псевдонимы:",
      "stake.title":"Стейк — заблокировать / разблокировать","stake.spendable":"Доступно","stake.bondAmount":"Сумма для стейка (NADO)","stake.unbondAmount":"Сумма для вывода (NADO)","btn.bond":"Заблокировать стейк","btn.unbond":"Разблокировать стейк","stake.autobond":"Авто-стейк наград","stake.noFee":"Без комиссии — разблокировка бесплатна.",
      "history.title":"История","btn.refresh":"Обновить",
      "explore.title":"Обзор","btn.search":"Поиск","explore.network":"Сеть","explore.mining":"Майнинг","explore.recent":"Недавние блоки",
      "settings.title":"Настройки","settings.relay":"URL узла-ретранслятора","btn.save":"Сохранить","btn.selftest":"Запустить самотест","btn.forget":"Забыть кошелёк"
    },
    zh: {
      "tab.wallet":"钱包","tab.send":"发送","tab.receive":"接收","tab.aliases":"别名","tab.stake":"质押","tab.history":"历史","tab.explore":"浏览","tab.settings":"设置",
      "app.sub":"仅浏览器 · 无需全节点","conn.connecting":"连接中…",
      "onboard.title":"开始","btn.genKey":"生成新密钥","btn.importKey":"导入密钥","btn.import":"导入",
      "save.title":"⚠ 保存你的私钥","save.ack":"我已保存私钥","save.continue":"继续 → 保存到本设备",
      "wallet.title":"钱包","lbl.address":"地址","lbl.free":"可用","lbl.bonded":"已质押","lbl.total":"总计","lbl.registered":"已注册","lbl.present":"在线","lbl.fidelity":"忠诚度","wallet.reveal":"显示 / 导出私钥","btn.dlKey":"⤓ 下载密钥文件 (JSON)",
      "mining.title":"挖矿","btn.startMining":"开始挖矿","btn.stopMining":"停止挖矿","mine.status":"状态","mine.epoch":"当前纪元","mine.eta":"预计出块时间","mine.nextHb":"下次心跳","mine.idle":"空闲",
      "lanes.title":"选择通道","lanes.open":"开放通道","lanes.bonded":"质押通道","lanes.openWeight":"开放权重","lanes.bondedShares":"质押份额",
      "send.title":"发送","send.recipient":"接收方地址","send.amount":"金额 (NADO)","send.fee":"网络费：","send.spendable":"可用余额：","btn.reviewSend":"确认并发送",
      "receive.title":"接收","receive.reqAmount":"请求金额 (NADO) — 可选","receive.payLink":"付款链接","receive.your":"你的地址","btn.copy":"复制","btn.share":"分享",
      "alias.title":"别名","alias.name":"别名","btn.register":"注册","btn.unregister":"注销","btn.transfer":"转移","alias.transferTo":"将所有权转移到 (ndo… 地址)","alias.your":"你的别名：",
      "stake.title":"质押 — 锁定 / 解锁","stake.spendable":"可用","stake.bondAmount":"锁定金额 (NADO)","stake.unbondAmount":"解锁金额 (NADO)","btn.bond":"锁定质押","btn.unbond":"解锁质押","stake.autobond":"自动质押挖矿奖励","stake.noFee":"无网络费 — 解锁免费。",
      "history.title":"历史","btn.refresh":"刷新",
      "explore.title":"浏览","btn.search":"搜索","explore.network":"网络","explore.mining":"挖矿","explore.recent":"最近区块",
      "settings.title":"设置","settings.relay":"中继节点 URL","btn.save":"保存","btn.selftest":"运行自检","btn.forget":"忘记钱包"
    },
    ja: {
      "tab.wallet":"ウォレット","tab.send":"送金","tab.receive":"受取","tab.aliases":"エイリアス","tab.stake":"ステーク","tab.history":"履歴","tab.explore":"エクスプローラ","tab.settings":"設定",
      "app.sub":"ブラウザのみ · フルノード不要","conn.connecting":"接続中…",
      "onboard.title":"はじめる","btn.genKey":"新しい鍵を生成","btn.importKey":"鍵をインポート","btn.import":"インポート",
      "save.title":"⚠ 秘密鍵を保存してください","save.ack":"秘密鍵を保存しました","save.continue":"続行 → この端末に保存",
      "wallet.title":"ウォレット","lbl.address":"アドレス","lbl.free":"利用可能","lbl.bonded":"ステーク中","lbl.total":"合計","lbl.registered":"登録済み","lbl.present":"参加中","lbl.fidelity":"継続度","wallet.reveal":"秘密鍵を表示 / エクスポート","btn.dlKey":"⤓ 鍵ファイルをダウンロード (JSON)",
      "mining.title":"マイニング","btn.startMining":"マイニング開始","btn.stopMining":"マイニング停止","mine.status":"状態","mine.epoch":"現在のエポック","mine.eta":"予想採掘時間","mine.nextHb":"次のハートビート","mine.idle":"待機中",
      "lanes.title":"選択レーン","lanes.open":"オープンレーン","lanes.bonded":"ステークレーン","lanes.openWeight":"オープン重み","lanes.bondedShares":"ステーク持分",
      "send.title":"送金","send.recipient":"受取人アドレス","send.amount":"金額 (NADO)","send.fee":"ネットワーク手数料:","send.spendable":"利用可能残高:","btn.reviewSend":"確認して送金",
      "receive.title":"受取","receive.reqAmount":"請求金額 (NADO) — 任意","receive.payLink":"支払いリンク","receive.your":"あなたのアドレス","btn.copy":"コピー","btn.share":"共有",
      "alias.title":"エイリアス","alias.name":"エイリアス名","btn.register":"登録","btn.unregister":"解除","btn.transfer":"譲渡","alias.transferTo":"所有権を譲渡 (ndo… アドレス)","alias.your":"あなたのエイリアス:",
      "stake.title":"ステーク — ボンド / アンボンド","stake.spendable":"利用可能","stake.bondAmount":"ボンド額 (NADO)","stake.unbondAmount":"アンボンド額 (NADO)","btn.bond":"ステークする","btn.unbond":"アンボンド","stake.autobond":"報酬を自動ステーク","stake.noFee":"手数料なし — アンボンドは無料です。",
      "history.title":"履歴","btn.refresh":"更新",
      "explore.title":"エクスプローラ","btn.search":"検索","explore.network":"ネットワーク","explore.mining":"マイニング","explore.recent":"最近のブロック",
      "settings.title":"設定","settings.relay":"リレーノード URL","btn.save":"保存","btn.selftest":"セルフテスト実行","btn.forget":"ウォレットを削除"
    },
    ko: {
      "tab.wallet":"지갑","tab.send":"보내기","tab.receive":"받기","tab.aliases":"별칭","tab.stake":"스테이킹","tab.history":"기록","tab.explore":"탐색","tab.settings":"설정",
      "app.sub":"브라우저 전용 · 풀노드 불필요","conn.connecting":"연결 중…",
      "onboard.title":"시작하기","btn.genKey":"새 키 생성","btn.importKey":"키 가져오기","btn.import":"가져오기",
      "save.title":"⚠ 개인 키를 저장하세요","save.ack":"개인 키를 저장했습니다","save.continue":"계속 → 이 기기에 저장",
      "wallet.title":"지갑","lbl.address":"주소","lbl.free":"사용 가능","lbl.bonded":"스테이크됨","lbl.total":"합계","lbl.registered":"등록됨","lbl.present":"활동 중","lbl.fidelity":"충실도","wallet.reveal":"개인 키 표시 / 내보내기","btn.dlKey":"⤓ 키 파일 다운로드 (JSON)",
      "mining.title":"채굴","btn.startMining":"채굴 시작","btn.stopMining":"채굴 중지","mine.status":"상태","mine.epoch":"현재 에포크","mine.eta":"예상 채굴 시간","mine.nextHb":"다음 하트비트","mine.idle":"대기",
      "lanes.title":"선택 레인","lanes.open":"공개 레인","lanes.bonded":"스테이크 레인","lanes.openWeight":"공개 가중치","lanes.bondedShares":"스테이크 지분",
      "send.title":"보내기","send.recipient":"받는 사람 주소","send.amount":"금액 (NADO)","send.fee":"네트워크 수수료:","send.spendable":"사용 가능 잔액:","btn.reviewSend":"확인 후 보내기",
      "receive.title":"받기","receive.reqAmount":"요청 금액 (NADO) — 선택","receive.payLink":"결제 링크","receive.your":"내 주소","btn.copy":"복사","btn.share":"공유",
      "alias.title":"별칭","alias.name":"별칭 이름","btn.register":"등록","btn.unregister":"해제","btn.transfer":"이전","alias.transferTo":"소유권 이전 대상 (ndo… 주소)","alias.your":"내 별칭:",
      "stake.title":"스테이킹 — 예치 / 해제","stake.spendable":"사용 가능","stake.bondAmount":"예치 금액 (NADO)","stake.unbondAmount":"해제 금액 (NADO)","btn.bond":"스테이크 예치","btn.unbond":"스테이크 해제","stake.autobond":"채굴 보상 자동 스테이크","stake.noFee":"수수료 없음 — 해제는 무료입니다.",
      "history.title":"기록","btn.refresh":"새로고침",
      "explore.title":"탐색","btn.search":"검색","explore.network":"네트워크","explore.mining":"채굴","explore.recent":"최근 블록",
      "settings.title":"설정","settings.relay":"릴레이 노드 URL","btn.save":"저장","btn.selftest":"자체 테스트 실행","btn.forget":"지갑 삭제"
    },
    ar: {
      "tab.wallet":"المحفظة","tab.send":"إرسال","tab.receive":"استلام","tab.aliases":"الأسماء","tab.stake":"التخزين","tab.history":"السجل","tab.explore":"استكشاف","tab.settings":"الإعدادات",
      "app.sub":"المتصفح فقط · بدون عقدة كاملة","conn.connecting":"جارٍ الاتصال…",
      "onboard.title":"ابدأ","btn.genKey":"إنشاء مفتاح جديد","btn.importKey":"استيراد مفتاح","btn.import":"استيراد",
      "save.title":"⚠ احفظ مفتاحك الخاص","save.ack":"لقد حفظت مفتاحي الخاص","save.continue":"متابعة ← التخزين على هذا الجهاز",
      "wallet.title":"المحفظة","lbl.address":"العنوان","lbl.free":"متاح","lbl.bonded":"مربوط","lbl.total":"الإجمالي","lbl.registered":"مسجَّل","lbl.present":"حاضر","lbl.fidelity":"الوفاء","wallet.reveal":"إظهار / تصدير المفتاح الخاص","btn.dlKey":"⤓ تنزيل ملف المفتاح (JSON)",
      "mining.title":"التعدين","btn.startMining":"بدء التعدين","btn.stopMining":"إيقاف التعدين","mine.status":"الحالة","mine.epoch":"الحقبة الحالية","mine.eta":"الوقت المتوقع للتعدين","mine.nextHb":"النبضة التالية","mine.idle":"خامل",
      "lanes.title":"مسارات الاختيار","lanes.open":"المسار المفتوح","lanes.bonded":"مسار التخزين","lanes.openWeight":"الوزن المفتوح","lanes.bondedShares":"حصص التخزين",
      "send.title":"إرسال","send.recipient":"عنوان المستلم","send.amount":"المبلغ (NADO)","send.fee":"رسوم الشبكة:","send.spendable":"الرصيد المتاح:","btn.reviewSend":"مراجعة وإرسال",
      "receive.title":"استلام","receive.reqAmount":"المبلغ المطلوب (NADO) — اختياري","receive.payLink":"رابط الدفع","receive.your":"عنوانك","btn.copy":"نسخ","btn.share":"مشاركة",
      "alias.title":"الأسماء","alias.name":"الاسم","btn.register":"تسجيل","btn.unregister":"إلغاء","btn.transfer":"نقل","alias.transferTo":"نقل الملكية إلى (عنوان ndo…)","alias.your":"أسماؤك:",
      "stake.title":"التخزين — ربط / فك","stake.spendable":"متاح","stake.bondAmount":"مبلغ الربط (NADO)","stake.unbondAmount":"مبلغ الفك (NADO)","btn.bond":"ربط التخزين","btn.unbond":"فك التخزين","stake.autobond":"ربط مكافآت التعدين تلقائيًا","stake.noFee":"لا رسوم — الفك مجاني.",
      "history.title":"السجل","btn.refresh":"تحديث",
      "explore.title":"استكشاف","btn.search":"بحث","explore.network":"الشبكة","explore.mining":"التعدين","explore.recent":"أحدث الكتل",
      "settings.title":"الإعدادات","settings.relay":"رابط عقدة الترحيل","btn.save":"حفظ","btn.selftest":"تشغيل الاختبار الذاتي","btn.forget":"نسيان المحفظة"
    },
    hi: {
      "tab.wallet":"वॉलेट","tab.send":"भेजें","tab.receive":"प्राप्त करें","tab.aliases":"उपनाम","tab.stake":"स्टेक","tab.history":"इतिहास","tab.explore":"एक्सप्लोर","tab.settings":"सेटिंग्स",
      "app.sub":"केवल ब्राउज़र · कोई फुल नोड नहीं","conn.connecting":"कनेक्ट हो रहा है…",
      "onboard.title":"शुरू करें","btn.genKey":"नई कुंजी बनाएं","btn.importKey":"कुंजी आयात करें","btn.import":"आयात",
      "save.title":"⚠ अपनी निजी कुंजी सहेजें","save.ack":"मैंने अपनी निजी कुंजी सहेज ली है","save.continue":"जारी रखें → इस डिवाइस पर सहेजें",
      "wallet.title":"वॉलेट","lbl.address":"पता","lbl.free":"उपलब्ध","lbl.bonded":"बॉन्डेड","lbl.total":"कुल","lbl.registered":"पंजीकृत","lbl.present":"मौजूद","lbl.fidelity":"निष्ठा","wallet.reveal":"निजी कुंजी दिखाएं / निर्यात करें","btn.dlKey":"⤓ कुंजी फ़ाइल डाउनलोड करें (JSON)",
      "mining.title":"माइनिंग","btn.startMining":"माइनिंग शुरू करें","btn.stopMining":"माइनिंग रोकें","mine.status":"स्थिति","mine.epoch":"वर्तमान एपोक","mine.eta":"माइन करने का अनुमानित समय","mine.nextHb":"अगला हार्टबीट","mine.idle":"निष्क्रिय",
      "lanes.title":"चयन लेन","lanes.open":"ओपन लेन","lanes.bonded":"बॉन्डेड लेन","lanes.openWeight":"ओपन भार","lanes.bondedShares":"बॉन्डेड शेयर",
      "send.title":"भेजें","send.recipient":"प्राप्तकर्ता का पता","send.amount":"राशि (NADO)","send.fee":"नेटवर्क शुल्क:","send.spendable":"खर्च योग्य शेष:","btn.reviewSend":"समीक्षा करें और भेजें",
      "receive.title":"प्राप्त करें","receive.reqAmount":"अनुरोधित राशि (NADO) — वैकल्पिक","receive.payLink":"भुगतान लिंक","receive.your":"आपका पता","btn.copy":"कॉपी","btn.share":"साझा करें",
      "alias.title":"उपनाम","alias.name":"उपनाम","btn.register":"पंजीकरण","btn.unregister":"रद्द करें","btn.transfer":"स्थानांतरण","alias.transferTo":"स्वामित्व स्थानांतरित करें (ndo… पता)","alias.your":"आपके उपनाम:",
      "stake.title":"स्टेक — बॉन्ड / अनबॉन्ड","stake.spendable":"उपलब्ध","stake.bondAmount":"बॉन्ड राशि (NADO)","stake.unbondAmount":"अनबॉन्ड राशि (NADO)","btn.bond":"स्टेक बॉन्ड करें","btn.unbond":"स्टेक अनबॉन्ड करें","stake.autobond":"माइनिंग इनाम ऑटो-बॉन्ड","stake.noFee":"कोई नेटवर्क शुल्क नहीं — अनबॉन्ड मुफ़्त है।",
      "history.title":"इतिहास","btn.refresh":"रिफ्रेश",
      "explore.title":"एक्सप्लोर","btn.search":"खोजें","explore.network":"नेटवर्क","explore.mining":"माइनिंग","explore.recent":"हाल के ब्लॉक",
      "settings.title":"सेटिंग्स","settings.relay":"रिले नोड URL","btn.save":"सहेजें","btn.selftest":"सेल्फ-टेस्ट चलाएं","btn.forget":"वॉलेट भूल जाएं"
    },
    tr: {
      "tab.wallet":"Cüzdan","tab.send":"Gönder","tab.receive":"Al","tab.aliases":"Takma adlar","tab.stake":"Stake","tab.history":"Geçmiş","tab.explore":"Keşfet","tab.settings":"Ayarlar",
      "app.sub":"yalnızca tarayıcı · tam düğüm yok","conn.connecting":"bağlanıyor…",
      "onboard.title":"Başla","btn.genKey":"Yeni anahtar oluştur","btn.importKey":"Anahtar içe aktar","btn.import":"İçe aktar",
      "save.title":"⚠ Özel anahtarınızı kaydedin","save.ack":"Özel anahtarımı kaydettim","save.continue":"Devam → bu cihaza kaydet",
      "wallet.title":"Cüzdan","lbl.address":"Adres","lbl.free":"Kullanılabilir","lbl.bonded":"Stake'te","lbl.total":"Toplam","lbl.registered":"Kayıtlı","lbl.present":"Aktif","lbl.fidelity":"Sadakat","wallet.reveal":"Özel anahtarı göster / dışa aktar","btn.dlKey":"⤓ Anahtar dosyasını indir (JSON)",
      "mining.title":"Madencilik","btn.startMining":"Madenciliği başlat","btn.stopMining":"Madenciliği durdur","mine.status":"Durum","mine.epoch":"Geçerli dönem","mine.eta":"Tahmini madencilik süresi","mine.nextHb":"Sonraki sinyal","mine.idle":"Boşta",
      "lanes.title":"Seçim şeritleri","lanes.open":"Açık şerit","lanes.bonded":"Stake şeridi","lanes.openWeight":"Açık ağırlık","lanes.bondedShares":"Stake payları",
      "send.title":"Gönder","send.recipient":"Alıcı adresi","send.amount":"Miktar (NADO)","send.fee":"Ağ ücreti:","send.spendable":"Harcanabilir bakiye:","btn.reviewSend":"İncele ve gönder",
      "receive.title":"Al","receive.reqAmount":"İstenen miktar (NADO) — isteğe bağlı","receive.payLink":"Ödeme bağlantısı","receive.your":"Adresiniz","btn.copy":"Kopyala","btn.share":"Paylaş",
      "alias.title":"Takma adlar","alias.name":"Takma ad","btn.register":"Kaydet","btn.unregister":"Kaldır","btn.transfer":"Aktar","alias.transferTo":"Sahipliği şuraya aktar (ndo… adresi)","alias.your":"Takma adlarınız:",
      "stake.title":"Stake — bağla / çöz","stake.spendable":"Kullanılabilir","stake.bondAmount":"Bağlama miktarı (NADO)","stake.unbondAmount":"Çözme miktarı (NADO)","btn.bond":"Stake'e bağla","btn.unbond":"Stake'i çöz","stake.autobond":"Madencilik ödüllerini otomatik stake et","stake.noFee":"Ağ ücreti yok — çözme ücretsizdir.",
      "history.title":"Geçmiş","btn.refresh":"Yenile",
      "explore.title":"Keşfet","btn.search":"Ara","explore.network":"Ağ","explore.mining":"Madencilik","explore.recent":"Son bloklar",
      "settings.title":"Ayarlar","settings.relay":"Röle düğümü URL'si","btn.save":"Kaydet","btn.selftest":"Otomatik testi çalıştır","btn.forget":"Cüzdanı unut"
    },
    id: {
      "tab.wallet":"Dompet","tab.send":"Kirim","tab.receive":"Terima","tab.aliases":"Alias","tab.stake":"Stake","tab.history":"Riwayat","tab.explore":"Jelajah","tab.settings":"Pengaturan",
      "app.sub":"hanya browser · tanpa node penuh","conn.connecting":"menghubungkan…",
      "onboard.title":"Mulai","btn.genKey":"Buat kunci baru","btn.importKey":"Impor kunci","btn.import":"Impor",
      "save.title":"⚠ Simpan kunci privat Anda","save.ack":"Saya sudah menyimpan kunci privat","save.continue":"Lanjut → simpan di perangkat ini",
      "wallet.title":"Dompet","lbl.address":"Alamat","lbl.free":"Tersedia","lbl.bonded":"Di-stake","lbl.total":"Total","lbl.registered":"Terdaftar","lbl.present":"Hadir","lbl.fidelity":"Loyalitas","wallet.reveal":"Tampilkan / ekspor kunci privat","btn.dlKey":"⤓ Unduh berkas kunci (JSON)",
      "mining.title":"Menambang","btn.startMining":"Mulai menambang","btn.stopMining":"Hentikan menambang","mine.status":"Status","mine.epoch":"Epoch saat ini","mine.eta":"Perkiraan waktu menambang","mine.nextHb":"Heartbeat berikutnya","mine.idle":"Diam",
      "lanes.title":"Jalur seleksi","lanes.open":"Jalur terbuka","lanes.bonded":"Jalur stake","lanes.openWeight":"Bobot terbuka","lanes.bondedShares":"Bagian stake",
      "send.title":"Kirim","send.recipient":"Alamat penerima","send.amount":"Jumlah (NADO)","send.fee":"Biaya jaringan:","send.spendable":"Saldo tersedia:","btn.reviewSend":"Tinjau & kirim",
      "receive.title":"Terima","receive.reqAmount":"Jumlah diminta (NADO) — opsional","receive.payLink":"Tautan pembayaran","receive.your":"Alamat Anda","btn.copy":"Salin","btn.share":"Bagikan",
      "alias.title":"Alias","alias.name":"Nama alias","btn.register":"Daftar","btn.unregister":"Batalkan","btn.transfer":"Transfer","alias.transferTo":"Transfer kepemilikan ke (alamat ndo…)","alias.your":"Alias Anda:",
      "stake.title":"Stake — kunci / buka","stake.spendable":"Tersedia","stake.bondAmount":"Jumlah dikunci (NADO)","stake.unbondAmount":"Jumlah dibuka (NADO)","btn.bond":"Kunci stake","btn.unbond":"Buka stake","stake.autobond":"Auto-stake hadiah menambang","stake.noFee":"Tanpa biaya — membuka gratis.",
      "history.title":"Riwayat","btn.refresh":"Segarkan",
      "explore.title":"Jelajah","btn.search":"Cari","explore.network":"Jaringan","explore.mining":"Menambang","explore.recent":"Blok terbaru",
      "settings.title":"Pengaturan","settings.relay":"URL node relai","btn.save":"Simpan","btn.selftest":"Jalankan uji mandiri","btn.forget":"Lupakan dompet"
    },
    vi: {
      "tab.wallet":"Ví","tab.send":"Gửi","tab.receive":"Nhận","tab.aliases":"Bí danh","tab.stake":"Đặt cược","tab.history":"Lịch sử","tab.explore":"Khám phá","tab.settings":"Cài đặt",
      "app.sub":"chỉ trình duyệt · không cần node đầy đủ","conn.connecting":"đang kết nối…",
      "onboard.title":"Bắt đầu","btn.genKey":"Tạo khóa mới","btn.importKey":"Nhập khóa","btn.import":"Nhập",
      "save.title":"⚠ Lưu khóa riêng của bạn","save.ack":"Tôi đã lưu khóa riêng","save.continue":"Tiếp tục → lưu trên thiết bị này",
      "wallet.title":"Ví","lbl.address":"Địa chỉ","lbl.free":"Khả dụng","lbl.bonded":"Đã đặt cược","lbl.total":"Tổng","lbl.registered":"Đã đăng ký","lbl.present":"Đang hoạt động","lbl.fidelity":"Độ trung thành","wallet.reveal":"Hiện / xuất khóa riêng","btn.dlKey":"⤓ Tải tệp khóa (JSON)",
      "mining.title":"Đào","btn.startMining":"Bắt đầu đào","btn.stopMining":"Dừng đào","mine.status":"Trạng thái","mine.epoch":"Kỷ nguyên hiện tại","mine.eta":"Thời gian đào dự kiến","mine.nextHb":"Nhịp tiếp theo","mine.idle":"Nhàn rỗi",
      "lanes.title":"Làn chọn","lanes.open":"Làn mở","lanes.bonded":"Làn đặt cược","lanes.openWeight":"Trọng số mở","lanes.bondedShares":"Cổ phần đặt cược",
      "send.title":"Gửi","send.recipient":"Địa chỉ người nhận","send.amount":"Số lượng (NADO)","send.fee":"Phí mạng:","send.spendable":"Số dư khả dụng:","btn.reviewSend":"Xem lại & gửi",
      "receive.title":"Nhận","receive.reqAmount":"Số tiền yêu cầu (NADO) — tùy chọn","receive.payLink":"Liên kết thanh toán","receive.your":"Địa chỉ của bạn","btn.copy":"Sao chép","btn.share":"Chia sẻ",
      "alias.title":"Bí danh","alias.name":"Tên bí danh","btn.register":"Đăng ký","btn.unregister":"Hủy đăng ký","btn.transfer":"Chuyển","alias.transferTo":"Chuyển quyền sở hữu tới (địa chỉ ndo…)","alias.your":"Bí danh của bạn:",
      "stake.title":"Đặt cược — khóa / mở","stake.spendable":"Khả dụng","stake.bondAmount":"Số tiền khóa (NADO)","stake.unbondAmount":"Số tiền mở (NADO)","btn.bond":"Khóa đặt cược","btn.unbond":"Mở đặt cược","stake.autobond":"Tự động đặt cược phần thưởng","stake.noFee":"Không phí — mở khóa miễn phí.",
      "history.title":"Lịch sử","btn.refresh":"Làm mới",
      "explore.title":"Khám phá","btn.search":"Tìm","explore.network":"Mạng","explore.mining":"Đào","explore.recent":"Khối gần đây",
      "settings.title":"Cài đặt","settings.relay":"URL node chuyển tiếp","btn.save":"Lưu","btn.selftest":"Chạy tự kiểm tra","btn.forget":"Quên ví"
    }
  };

  // Additional on-screen strings (badges, dynamic mining states, lane legend, short prose) merged into T.
  // Short strings are provided for every language; longer prose only where confident (else English fallback).
  const T2 = {
    en: { "lane.miners":"miners","lane.validators":"validators","lane.legendOpen":"Open lane — free, capital-less (you)","lane.legendBonded":"Bonded lane — locked stake","badge.yes":"yes","badge.no":"no","badge.new":"new","badge.present":"present","badge.absent":"absent","mine.starting":"Starting…","mine.mining":"Mining","mine.registering":"Registering…","mine.stopped":"Stopped","log.title":"Activity","btn.clear":"Clear","alias.your":"Your aliases:","alias.pill":"a name instead of a hash",
      "onboard.intro":"Generate a brand-new mining identity or import an existing private key. Everything happens locally in your browser — your private key never leaves this device.",
      "receive.intro":"Share this QR or payment link to request NADO. Scanning it opens a wallet with a Send pre-filled — the sender always reviews and confirms before anything is sent.",
      "alias.intro":"Register a short name that resolves to your own address — others can then send to the name instead of your long ndo… address. Names are global and first-come; registering costs a small anti-squat fee.",
      "settings.relayNote":"Defaults to this page's origin. A custom relay must be same-origin or send CORS headers, or your browser will block reads.",
      "footer":"NADO light-miner · the chain stays on full nodes; this page only generates keys, registers, and heartbeats. Your reward lands on your address because a relay builds the block crediting it." },
    cs: { "lane.miners":"těžařů","lane.validators":"validátorů","lane.legendOpen":"Otevřená dráha — zdarma, bez kapitálu (vy)","lane.legendBonded":"Staking dráha — uzamčený stake","badge.yes":"ano","badge.no":"ne","badge.new":"nový","badge.present":"přítomen","badge.absent":"nepřítomen","mine.starting":"Spouštění…","mine.mining":"Těžba","mine.registering":"Registrace…","mine.stopped":"Zastaveno","log.title":"Aktivita","btn.clear":"Vymazat","alias.your":"Vaše aliasy:","alias.pill":"jméno místo hashe",
      "onboard.intro":"Vytvořte zcela novou těžební identitu nebo naimportujte existující soukromý klíč. Vše probíhá lokálně ve vašem prohlížeči — váš soukromý klíč nikdy neopustí toto zařízení.",
      "receive.intro":"Sdílejte tento QR kód nebo platební odkaz pro vyžádání NADO. Naskenováním se otevře peněženka s předvyplněným odesláním — odesílatel vždy zkontroluje a potvrdí, než se cokoli odešle.",
      "alias.intro":"Zaregistrujte si krátké jméno, které odkazuje na vaši vlastní adresu — ostatní pak mohou posílat na jméno místo vaší dlouhé ndo… adresy. Jména jsou globální a platí kdo dřív přijde; registrace stojí malý poplatek proti squattingu.",
      "settings.relayNote":"Výchozí je původ této stránky. Vlastní relay musí být ze stejného původu nebo posílat hlavičky CORS, jinak prohlížeč čtení zablokuje.",
      "footer":"NADO light-miner · řetězec zůstává na plných uzlech; tato stránka jen generuje klíče, registruje a posílá tepy. Vaše odměna přistane na vaší adrese, protože relay sestaví blok, který ji připíše." },
    es: { "lane.miners":"mineros","lane.validators":"validadores","lane.legendOpen":"Carril abierto — gratis, sin capital (tú)","lane.legendBonded":"Carril con stake — bloqueado","badge.yes":"sí","badge.no":"no","badge.new":"nuevo","badge.present":"presente","badge.absent":"ausente","mine.starting":"Iniciando…","mine.mining":"Minando","mine.registering":"Registrando…","mine.stopped":"Detenido","log.title":"Actividad","btn.clear":"Limpiar","alias.your":"Tus alias:","alias.pill":"un nombre en vez de un hash",
      "onboard.intro":"Genera una identidad de minería nueva o importa una clave privada existente. Todo ocurre localmente en tu navegador — tu clave privada nunca sale de este dispositivo.",
      "receive.intro":"Comparte este QR o enlace de pago para solicitar NADO. Al escanearlo se abre una cartera con un envío ya preparado — el remitente siempre revisa y confirma antes de enviar.",
      "alias.intro":"Registra un nombre corto que apunta a tu propia dirección — así otros pueden enviar al nombre en vez de a tu larga dirección ndo…. Los nombres son globales y por orden de llegada; registrar cuesta una pequeña comisión anti-ocupación.",
      "settings.relayNote":"Por defecto usa el origen de esta página. Un relé personalizado debe ser del mismo origen o enviar cabeceras CORS, o el navegador bloqueará las lecturas.",
      "footer":"NADO light-miner · la cadena vive en los nodos completos; esta página solo genera claves, registra y late. Tu recompensa llega a tu dirección porque un relé construye el bloque que la acredita." },
    pt: { "lane.miners":"mineradores","lane.validators":"validadores","lane.legendOpen":"Faixa aberta — grátis, sem capital (você)","lane.legendBonded":"Faixa com stake — bloqueado","badge.yes":"sim","badge.no":"não","badge.new":"novo","badge.present":"presente","badge.absent":"ausente","mine.starting":"Iniciando…","mine.mining":"Minerando","mine.registering":"Registando…","mine.stopped":"Parado","log.title":"Atividade","btn.clear":"Limpar","alias.your":"Os seus apelidos:","alias.pill":"um nome em vez de um hash",
      "onboard.intro":"Gere uma identidade de mineração nova ou importe uma chave privada existente. Tudo acontece localmente no seu navegador — a sua chave privada nunca sai deste dispositivo.",
      "receive.intro":"Partilhe este QR ou link de pagamento para pedir NADO. Ao lê-lo abre-se uma carteira com um envio pré-preenchido — o remetente revê e confirma sempre antes de enviar.",
      "alias.intro":"Registe um nome curto que aponta para o seu próprio endereço — outros podem então enviar para o nome em vez do seu longo endereço ndo…. Os nomes são globais e por ordem de chegada; registar custa uma pequena taxa anti-ocupação.",
      "settings.relayNote":"Por padrão usa a origem desta página. Um relé personalizado tem de ser da mesma origem ou enviar cabeçalhos CORS, senão o navegador bloqueia as leituras.",
      "footer":"NADO light-miner · a cadeia fica nos nós completos; esta página só gera chaves, regista e envia batimentos. A sua recompensa chega ao seu endereço porque um relé constrói o bloco que a credita." },
    fr: { "lane.miners":"mineurs","lane.validators":"validateurs","lane.legendOpen":"Voie ouverte — gratuite, sans capital (vous)","lane.legendBonded":"Voie stakée — verrouillée","badge.yes":"oui","badge.no":"non","badge.new":"nouveau","badge.present":"présent","badge.absent":"absent","mine.starting":"Démarrage…","mine.mining":"Minage","mine.registering":"Enregistrement…","mine.stopped":"Arrêté","log.title":"Activité","btn.clear":"Effacer","alias.your":"Vos alias :","alias.pill":"un nom au lieu d'un hash",
      "onboard.intro":"Générez une toute nouvelle identité de minage ou importez une clé privée existante. Tout se passe localement dans votre navigateur — votre clé privée ne quitte jamais cet appareil.",
      "receive.intro":"Partagez ce QR ou ce lien de paiement pour demander des NADO. Le scanner ouvre un portefeuille avec un envoi pré-rempli — l'expéditeur vérifie et confirme toujours avant tout envoi.",
      "alias.intro":"Enregistrez un nom court qui pointe vers votre propre adresse — les autres peuvent alors envoyer au nom plutôt qu'à votre longue adresse ndo…. Les noms sont globaux et au premier arrivé ; l'enregistrement coûte de petits frais anti-squat.",
      "settings.relayNote":"Par défaut, l'origine de cette page. Un relais personnalisé doit être de même origine ou envoyer des en-têtes CORS, sinon votre navigateur bloquera les lectures.",
      "footer":"NADO light-miner · la chaîne reste sur les nœuds complets ; cette page ne fait que générer des clés, s'enregistrer et battre. Votre récompense arrive à votre adresse car un relais construit le bloc qui la crédite." },
    de: { "lane.miners":"Miner","lane.validators":"Validatoren","lane.legendOpen":"Offene Spur — kostenlos, ohne Kapital (du)","lane.legendBonded":"Gebundene Spur — gesperrter Stake","badge.yes":"ja","badge.no":"nein","badge.new":"neu","badge.present":"anwesend","badge.absent":"abwesend","mine.starting":"Starte…","mine.mining":"Mining","mine.registering":"Registriere…","mine.stopped":"Gestoppt","log.title":"Aktivität","btn.clear":"Leeren","alias.your":"Deine Aliase:","alias.pill":"ein Name statt eines Hashes",
      "onboard.intro":"Erzeuge eine brandneue Mining-Identität oder importiere einen vorhandenen privaten Schlüssel. Alles geschieht lokal in deinem Browser — dein privater Schlüssel verlässt dieses Gerät nie.",
      "receive.intro":"Teile diesen QR-Code oder Zahlungslink, um NADO anzufordern. Beim Scannen öffnet sich eine Wallet mit vorausgefülltem Senden — der Absender prüft und bestätigt immer, bevor etwas gesendet wird.",
      "alias.intro":"Registriere einen kurzen Namen, der auf deine eigene Adresse verweist — andere können dann an den Namen statt an deine lange ndo…-Adresse senden. Namen sind global und wer zuerst kommt; die Registrierung kostet eine kleine Anti-Squat-Gebühr.",
      "settings.relayNote":"Standard ist der Ursprung dieser Seite. Ein eigener Relay muss vom selben Ursprung sein oder CORS-Header senden, sonst blockiert der Browser die Lesezugriffe.",
      "footer":"NADO light-miner · die Kette bleibt auf Full Nodes; diese Seite erzeugt nur Schlüssel, registriert und sendet Heartbeats. Deine Belohnung landet auf deiner Adresse, weil ein Relay den gutschreibenden Block baut." },
    it: { "lane.miners":"minatori","lane.validators":"validatori","lane.legendOpen":"Corsia aperta — gratis, senza capitale (tu)","lane.legendBonded":"Corsia in stake — bloccata","badge.yes":"sì","badge.no":"no","badge.new":"nuovo","badge.present":"presente","badge.absent":"assente","mine.starting":"Avvio…","mine.mining":"Mining","mine.registering":"Registrazione…","mine.stopped":"Fermato","log.title":"Attività","btn.clear":"Pulisci","alias.your":"I tuoi alias:","alias.pill":"un nome invece di un hash",
      "onboard.intro":"Genera una nuova identità di mining o importa una chiave privata esistente. Tutto avviene localmente nel tuo browser — la tua chiave privata non lascia mai questo dispositivo.",
      "receive.intro":"Condividi questo QR o link di pagamento per richiedere NADO. Scansionandolo si apre un portafoglio con un invio precompilato — il mittente controlla e conferma sempre prima di inviare.",
      "alias.intro":"Registra un nome breve che punta al tuo indirizzo — gli altri possono poi inviare al nome invece del tuo lungo indirizzo ndo…. I nomi sono globali e a chi arriva prima; registrare costa una piccola commissione anti-squat.",
      "settings.relayNote":"Predefinito è l'origine di questa pagina. Un relay personalizzato deve essere della stessa origine o inviare header CORS, altrimenti il browser bloccherà le letture.",
      "footer":"NADO light-miner · la catena resta sui nodi completi; questa pagina genera solo chiavi, registra e invia battiti. La tua ricompensa arriva al tuo indirizzo perché un relay costruisce il blocco che la accredita." },
    ru: { "lane.miners":"майнеров","lane.validators":"валидаторов","lane.legendOpen":"Открытая полоса — бесплатно, без капитала (вы)","lane.legendBonded":"Полоса стейка — заблокировано","badge.yes":"да","badge.no":"нет","badge.new":"новый","badge.present":"активен","badge.absent":"отсутствует","mine.starting":"Запуск…","mine.mining":"Майнинг","mine.registering":"Регистрация…","mine.stopped":"Остановлено","log.title":"Активность","btn.clear":"Очистить","alias.your":"Ваши псевдонимы:","alias.pill":"имя вместо хеша",
      "onboard.intro":"Создайте совершенно новую майнинг-личность или импортируйте существующий приватный ключ. Всё происходит локально в вашем браузере — приватный ключ никогда не покидает это устройство.",
      "receive.intro":"Поделитесь этим QR или платёжной ссылкой, чтобы запросить NADO. При сканировании откроется кошелёк с предзаполненной отправкой — отправитель всегда проверяет и подтверждает перед отправкой.",
      "alias.intro":"Зарегистрируйте короткое имя, указывающее на ваш адрес — другие смогут отправлять на имя вместо вашего длинного адреса ndo…. Имена глобальны и по очереди; регистрация стоит небольшую комиссию против сквоттинга.",
      "settings.relayNote":"По умолчанию — источник этой страницы. Свой релей должен быть того же источника или слать заголовки CORS, иначе браузер заблокирует чтение.",
      "footer":"NADO light-miner · цепь живёт на полных узлах; эта страница только генерирует ключи, регистрирует и шлёт сигналы. Ваша награда попадает на ваш адрес, потому что релей строит блок, зачисляющий её." },
    zh: { "lane.miners":"矿工","lane.validators":"验证者","lane.legendOpen":"开放通道 — 免费、无需资本（你）","lane.legendBonded":"质押通道 — 锁定的质押","badge.yes":"是","badge.no":"否","badge.new":"新","badge.present":"在线","badge.absent":"离线","mine.starting":"启动中…","mine.mining":"挖矿中","mine.registering":"注册中…","mine.stopped":"已停止","log.title":"活动","btn.clear":"清除","alias.your":"你的别名：","alias.pill":"用名字代替哈希",
      "onboard.intro":"生成全新的挖矿身份，或导入已有的私钥。一切都在你的浏览器本地进行——你的私钥永远不会离开本设备。",
      "receive.intro":"分享此二维码或付款链接以请求 NADO。扫描后会打开一个预填发送的钱包——发送方在发送前始终会审核并确认。",
      "alias.intro":"注册一个指向你自己地址的短名字——别人就能发送到名字而不是你冗长的 ndo… 地址。名字是全局的、先到先得；注册需付一小笔防抢注费用。",
      "settings.relayNote":"默认使用本页面的来源。自定义中继必须同源或发送 CORS 头，否则浏览器会阻止读取。",
      "footer":"NADO 轻矿工 · 链保存在全节点上；本页面只生成密钥、注册并发送心跳。你的奖励会到你的地址，因为中继会构建为其记账的区块。" },
    ja: { "lane.miners":"マイナー","lane.validators":"バリデータ","lane.legendOpen":"オープンレーン — 無料・資本不要（あなた）","lane.legendBonded":"ステークレーン — ロック済み","badge.yes":"はい","badge.no":"いいえ","badge.new":"新規","badge.present":"参加中","badge.absent":"不在","mine.starting":"開始中…","mine.mining":"マイニング中","mine.registering":"登録中…","mine.stopped":"停止","log.title":"アクティビティ","btn.clear":"クリア","alias.your":"あなたのエイリアス:","alias.pill":"ハッシュの代わりに名前",
      "onboard.intro":"新しいマイニングIDを生成するか、既存の秘密鍵をインポートします。すべてブラウザ内でローカルに行われ、秘密鍵がこの端末から出ることはありません。",
      "receive.intro":"このQRまたは支払いリンクを共有してNADOを請求します。スキャンすると送金が事前入力されたウォレットが開きます — 送信者は送信前に必ず確認します。",
      "alias.intro":"自分のアドレスを指す短い名前を登録します — 他の人は長い ndo… アドレスの代わりに名前へ送れます。名前はグローバルで先着順、登録には少額のスクワット防止手数料がかかります。",
      "settings.relayNote":"既定はこのページのオリジンです。カスタムリレーは同一オリジンか、CORSヘッダーを送る必要があります。さもないとブラウザが読み取りをブロックします。",
      "footer":"NADO ライトマイナー · チェーンはフルノードに置かれます。このページは鍵の生成・登録・ハートビートのみ行います。リレーが加算ブロックを作るため、報酬はあなたのアドレスに届きます。" },
    ko: { "lane.miners":"채굴자","lane.validators":"검증자","lane.legendOpen":"공개 레인 — 무료, 자본 불필요 (당신)","lane.legendBonded":"스테이크 레인 — 잠긴 스테이크","badge.yes":"예","badge.no":"아니오","badge.new":"신규","badge.present":"활동 중","badge.absent":"부재","mine.starting":"시작 중…","mine.mining":"채굴 중","mine.registering":"등록 중…","mine.stopped":"중지됨","log.title":"활동","btn.clear":"지우기","alias.your":"내 별칭:","alias.pill":"해시 대신 이름" },
    ar: { "lane.miners":"المُعدِّنون","lane.validators":"المُصادِقون","lane.legendOpen":"المسار المفتوح — مجاني، دون رأس مال (أنت)","lane.legendBonded":"مسار التخزين — مربوط","badge.yes":"نعم","badge.no":"لا","badge.new":"جديد","badge.present":"حاضر","badge.absent":"غائب","mine.starting":"جارٍ البدء…","mine.mining":"يُعدِّن","mine.registering":"جارٍ التسجيل…","mine.stopped":"متوقف","log.title":"النشاط","btn.clear":"مسح","alias.your":"أسماؤك:","alias.pill":"اسم بدلاً من التجزئة" },
    hi: { "lane.miners":"माइनर","lane.validators":"वैलिडेटर","lane.legendOpen":"ओपन लेन — मुफ़्त, बिना पूंजी (आप)","lane.legendBonded":"बॉन्डेड लेन — लॉक किया स्टेक","badge.yes":"हाँ","badge.no":"नहीं","badge.new":"नया","badge.present":"मौजूद","badge.absent":"अनुपस्थित","mine.starting":"शुरू हो रहा…","mine.mining":"माइनिंग","mine.registering":"पंजीकरण…","mine.stopped":"रुका","log.title":"गतिविधि","btn.clear":"साफ़ करें","alias.your":"आपके उपनाम:","alias.pill":"हैश के बजाय एक नाम" },
    tr: { "lane.miners":"madenci","lane.validators":"doğrulayıcı","lane.legendOpen":"Açık şerit — ücretsiz, sermayesiz (siz)","lane.legendBonded":"Stake şeridi — kilitli","badge.yes":"evet","badge.no":"hayır","badge.new":"yeni","badge.present":"aktif","badge.absent":"yok","mine.starting":"Başlatılıyor…","mine.mining":"Madencilik","mine.registering":"Kaydediliyor…","mine.stopped":"Durduruldu","log.title":"Etkinlik","btn.clear":"Temizle","alias.your":"Takma adlarınız:","alias.pill":"hash yerine bir isim" },
    id: { "lane.miners":"penambang","lane.validators":"validator","lane.legendOpen":"Jalur terbuka — gratis, tanpa modal (Anda)","lane.legendBonded":"Jalur stake — terkunci","badge.yes":"ya","badge.no":"tidak","badge.new":"baru","badge.present":"hadir","badge.absent":"tidak hadir","mine.starting":"Memulai…","mine.mining":"Menambang","mine.registering":"Mendaftar…","mine.stopped":"Berhenti","log.title":"Aktivitas","btn.clear":"Bersihkan","alias.your":"Alias Anda:","alias.pill":"nama alih-alih hash" },
    vi: { "lane.miners":"thợ đào","lane.validators":"trình xác thực","lane.legendOpen":"Làn mở — miễn phí, không cần vốn (bạn)","lane.legendBonded":"Làn đặt cược — đã khóa","badge.yes":"có","badge.no":"không","badge.new":"mới","badge.present":"đang hoạt động","badge.absent":"vắng mặt","mine.starting":"Đang khởi động…","mine.mining":"Đang đào","mine.registering":"Đang đăng ký…","mine.stopped":"Đã dừng","log.title":"Hoạt động","btn.clear":"Xóa","alias.your":"Bí danh của bạn:","alias.pill":"tên thay cho hash" }
  };
  for (const l in T2) Object.assign(T[l] = T[l] || {}, T2[l]);

  // Prose for the remaining languages (so every language is 100% translated, no English fallback).
  const T3 = {
    ko: {
      "onboard.intro":"완전히 새로운 채굴 신원을 생성하거나 기존 개인 키를 가져오세요. 모든 것은 브라우저에서 로컬로 처리되며, 개인 키는 이 기기를 절대 벗어나지 않습니다.",
      "receive.intro":"이 QR 또는 결제 링크를 공유하여 NADO를 요청하세요. 스캔하면 보내기가 미리 채워진 지갑이 열립니다 — 보내는 사람은 항상 전송 전에 검토하고 확인합니다.",
      "alias.intro":"자신의 주소를 가리키는 짧은 이름을 등록하세요 — 그러면 다른 사람이 긴 ndo… 주소 대신 이름으로 보낼 수 있습니다. 이름은 전역적이며 선착순이고, 등록에는 소액의 선점 방지 수수료가 듭니다.",
      "settings.relayNote":"기본값은 이 페이지의 출처입니다. 사용자 지정 릴레이는 동일 출처이거나 CORS 헤더를 보내야 하며, 그렇지 않으면 브라우저가 읽기를 차단합니다.",
      "footer":"NADO 라이트 마이너 · 체인은 풀 노드에 저장됩니다. 이 페이지는 키 생성, 등록, 하트비트만 수행합니다. 릴레이가 적립 블록을 만들기 때문에 보상이 주소로 도착합니다." },
    ar: {
      "onboard.intro":"أنشئ هوية تعدين جديدة تمامًا أو استورد مفتاحًا خاصًا موجودًا. كل شيء يحدث محليًا في متصفحك — مفتاحك الخاص لا يغادر هذا الجهاز أبدًا.",
      "receive.intro":"شارك رمز QR أو رابط الدفع هذا لطلب NADO. مسحه يفتح محفظة بعملية إرسال معبأة مسبقًا — يراجع المرسل ويؤكد دائمًا قبل الإرسال.",
      "alias.intro":"سجّل اسمًا قصيرًا يشير إلى عنوانك — عندها يمكن للآخرين الإرسال إلى الاسم بدلًا من عنوانك الطويل ndo…. الأسماء عالمية ومن يسبق يربح؛ التسجيل يكلف رسمًا صغيرًا لمنع الاستحواذ.",
      "settings.relayNote":"الافتراضي هو أصل هذه الصفحة. يجب أن يكون المُرحّل المخصص من نفس الأصل أو يرسل ترويسات CORS، وإلا سيمنع المتصفح القراءة.",
      "footer":"NADO لايت ماينر · تبقى السلسلة على العقد الكاملة؛ هذه الصفحة تولّد المفاتيح وتسجّل وترسل النبضات فقط. تصل مكافأتك إلى عنوانك لأن المُرحّل يبني الكتلة التي تقيّدها." },
    hi: {
      "onboard.intro":"बिलकुल नई माइनिंग पहचान बनाएं या मौजूदा निजी कुंजी आयात करें। सब कुछ आपके ब्राउज़र में स्थानीय रूप से होता है — आपकी निजी कुंजी कभी इस डिवाइस से बाहर नहीं जाती।",
      "receive.intro":"NADO माँगने के लिए यह QR या भुगतान लिंक साझा करें। इसे स्कैन करने पर एक वॉलेट खुलता है जिसमें भेजना पहले से भरा होता है — भेजने वाला भेजने से पहले हमेशा जाँचता और पुष्टि करता है।",
      "alias.intro":"एक छोटा नाम पंजीकृत करें जो आपके अपने पते की ओर इशारा करता है — फिर दूसरे आपके लंबे ndo… पते के बजाय नाम पर भेज सकते हैं। नाम वैश्विक और पहले आओ पहले पाओ हैं; पंजीकरण में एक छोटा एंटी-स्क्वाट शुल्क लगता है।",
      "settings.relayNote":"डिफ़ॉल्ट इस पेज का मूल है। कस्टम रिले को समान-मूल होना चाहिए या CORS हेडर भेजने चाहिए, वरना आपका ब्राउज़र पढ़ना रोक देगा।",
      "footer":"NADO लाइट-माइनर · चेन फुल नोड्स पर रहती है; यह पेज केवल कुंजियाँ बनाता, पंजीकरण और हार्टबीट करता है। आपका इनाम आपके पते पर आता है क्योंकि एक रिले उसे क्रेडिट करने वाला ब्लॉक बनाता है।" },
    tr: {
      "onboard.intro":"Yepyeni bir madencilik kimliği oluşturun veya mevcut bir özel anahtarı içe aktarın. Her şey tarayıcınızda yerel olarak gerçekleşir — özel anahtarınız bu cihazdan asla çıkmaz.",
      "receive.intro":"NADO istemek için bu QR'ı veya ödeme bağlantısını paylaşın. Taranınca gönderimi önceden doldurulmuş bir cüzdan açılır — gönderen her zaman göndermeden önce inceler ve onaylar.",
      "alias.intro":"Kendi adresinize işaret eden kısa bir ad kaydedin — böylece başkaları uzun ndo… adresiniz yerine ada gönderebilir. Adlar geneldir ve ilk gelen alır; kayıt küçük bir işgal önleme ücreti alır.",
      "settings.relayNote":"Varsayılan olarak bu sayfanın kaynağıdır. Özel bir röle aynı kaynaktan olmalı veya CORS başlıkları göndermelidir, aksi halde tarayıcınız okumayı engeller.",
      "footer":"NADO hafif madenci · zincir tam düğümlerde kalır; bu sayfa yalnızca anahtar üretir, kaydeder ve sinyal gönderir. Bir röle onu kaydeden bloğu oluşturduğu için ödülünüz adresinize ulaşır." },
    id: {
      "onboard.intro":"Hasilkan identitas penambangan yang benar-benar baru atau impor kunci privat yang ada. Semuanya terjadi secara lokal di browser Anda — kunci privat Anda tidak pernah meninggalkan perangkat ini.",
      "receive.intro":"Bagikan QR atau tautan pembayaran ini untuk meminta NADO. Memindainya membuka dompet dengan pengiriman terisi otomatis — pengirim selalu meninjau dan mengonfirmasi sebelum mengirim.",
      "alias.intro":"Daftarkan nama pendek yang menunjuk ke alamat Anda sendiri — orang lain lalu bisa mengirim ke nama alih-alih alamat ndo… Anda yang panjang. Nama bersifat global dan siapa cepat dia dapat; pendaftaran dikenai biaya kecil anti-squat.",
      "settings.relayNote":"Bawaan adalah asal halaman ini. Relai khusus harus sama-asal atau mengirim header CORS, jika tidak browser Anda akan memblokir pembacaan.",
      "footer":"NADO light-miner · rantai tetap di node penuh; halaman ini hanya membuat kunci, mendaftar, dan mengirim heartbeat. Hadiah Anda sampai ke alamat Anda karena relai membangun blok yang mengkreditkannya." },
    vi: {
      "onboard.intro":"Tạo một danh tính đào hoàn toàn mới hoặc nhập khóa riêng hiện có. Mọi thứ diễn ra cục bộ trong trình duyệt của bạn — khóa riêng của bạn không bao giờ rời khỏi thiết bị này.",
      "receive.intro":"Chia sẻ mã QR hoặc liên kết thanh toán này để yêu cầu NADO. Quét nó sẽ mở ví với phần Gửi được điền sẵn — người gửi luôn xem lại và xác nhận trước khi gửi.",
      "alias.intro":"Đăng ký một tên ngắn trỏ đến địa chỉ của chính bạn — người khác có thể gửi đến tên thay vì địa chỉ ndo… dài của bạn. Tên có tính toàn cục và ai đến trước được trước; đăng ký tốn một khoản phí nhỏ chống chiếm chỗ.",
      "settings.relayNote":"Mặc định là nguồn gốc của trang này. Relay tùy chỉnh phải cùng nguồn gốc hoặc gửi tiêu đề CORS, nếu không trình duyệt sẽ chặn việc đọc.",
      "footer":"NADO light-miner · chuỗi nằm trên các node đầy đủ; trang này chỉ tạo khóa, đăng ký và gửi nhịp. Phần thưởng của bạn đến địa chỉ của bạn vì một relay xây dựng khối ghi có cho nó." }
  };
  for (const l in T3) Object.assign(T[l], T3[l]);

  const NAMES = { en:"English", cs:"Čeština", es:"Español", pt:"Português", fr:"Français", de:"Deutsch", it:"Italiano",
    ru:"Русский", zh:"中文", ja:"日本語", ko:"한국어", ar:"العربية", hi:"हिन्दी", tr:"Türkçe",
    id:"Bahasa Indonesia", vi:"Tiếng Việt" };
  const RTL = new Set(["ar", "fa", "he", "ur"]);

  function pickLang() {
    try { const s = localStorage.getItem("nado_lang"); if (s && T[s]) return s; } catch (e) {}
    const cands = navigator.languages && navigator.languages.length ? navigator.languages : [navigator.language || "en"];
    for (const c of cands) { const base = String(c).toLowerCase().split("-")[0]; if (T[base]) return base; }
    return "en";
  }
  let LANG = pickLang();

  function t(key, fb) { return (T[LANG] && T[LANG][key]) || T.en[key] || (fb != null ? fb : key); }

  // Replace ONLY an element's leading text node, so a translated label keeps its child nodes intact
  // (the ⓘ hint icons, .pill / .badge spans). Falls back to the current leading text if the key is missing.
  function _leadText(el) {
    const n = el.firstChild;
    return (n && n.nodeType === 3) ? n.nodeValue.trim() : el.textContent.trim();
  }
  function _setLead(el, val) {
    const n = el.firstChild;
    if (n && n.nodeType === 3) {
      const trail = /\s$/.test(n.nodeValue) ? " " : "";
      n.nodeValue = val + trail;
    } else {
      el.insertBefore(document.createTextNode(val + " "), el.firstChild);
    }
  }

  function applyI18n() {
    const html = document.documentElement;
    html.lang = LANG;
    html.dir = RTL.has(LANG) ? "rtl" : "ltr";
    document.querySelectorAll("[data-i18n]").forEach((el) => { _setLead(el, t(el.getAttribute("data-i18n"), _leadText(el))); });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.textContent = t(el.getAttribute("data-i18n-html"), el.textContent); });
    document.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.setAttribute("placeholder", t(el.getAttribute("data-i18n-ph"), el.getAttribute("placeholder"))); });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => { el.setAttribute("title", t(el.getAttribute("data-i18n-title"), el.getAttribute("title"))); });
    try { window.dispatchEvent(new CustomEvent("nado-lang", { detail: LANG })); } catch (e) {}
  }

  function setLang(l) {
    if (!T[l]) return;
    LANG = l;
    try { localStorage.setItem("nado_lang", l); } catch (e) {}
    applyI18n();
  }

  function buildPicker() {
    if (document.getElementById("langSelect")) return;
    const sel = document.createElement("select");
    sel.id = "langSelect";
    sel.setAttribute("aria-label", "Language");
    sel.style.cssText = "margin-top:4px;background:#0b0f14;color:inherit;border:1px solid #1c2530;border-radius:8px;padding:2px 6px;font-size:12px;max-width:150px";
    Object.keys(T).forEach((l) => {
      const o = document.createElement("option");
      o.value = l; o.textContent = NAMES[l] || l; if (l === LANG) o.selected = true;
      sel.appendChild(o);
    });
    sel.addEventListener("change", () => setLang(sel.value));
    const host = document.querySelector("header.app .conn") || document.querySelector("header.app") || document.body;
    host.appendChild(sel);
  }

  function init() { buildPicker(); applyI18n(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // expose for the miner module
  window.t = t;
  window.NADO_i18n = { t: t, setLang: setLang, apply: applyI18n, lang: function () { return LANG; }, langs: Object.keys(T) };
})();
