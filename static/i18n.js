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

  const NAMES = { en:"English", es:"Español", pt:"Português", fr:"Français", de:"Deutsch", it:"Italiano",
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

  function applyI18n() {
    const html = document.documentElement;
    html.lang = LANG;
    html.dir = RTL.has(LANG) ? "rtl" : "ltr";
    document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.getAttribute("data-i18n"), el.textContent); });
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
