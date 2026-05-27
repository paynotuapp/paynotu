import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:intl/intl.dart';

// ─── Model ───────────────────────────────────────────────────────────────────

class _Alinti {
  final String mesajId;
  final String mesaj;
  final String displayName;

  const _Alinti({
    required this.mesajId,
    required this.mesaj,
    required this.displayName,
  });

  Map<String, dynamic> toMap() => {
        'mesajId': mesajId,
        'mesaj': mesaj,
        'displayName': displayName,
      };

  factory _Alinti.fromMap(Map<String, dynamic> m) => _Alinti(
        mesajId: m['mesajId'] ?? '',
        mesaj: m['mesaj'] ?? '',
        displayName: m['displayName'] ?? '',
      );
}

// ─── Ana Widget ───────────────────────────────────────────────────────────────

class SohbetTab extends StatefulWidget {
  final String symbol;
  final String hisseAdi;
  const SohbetTab({super.key, required this.symbol, required this.hisseAdi});

  @override
  State<SohbetTab> createState() => _SohbetTabState();
}

class _SohbetTabState extends State<SohbetTab>
    with AutomaticKeepAliveClientMixin {
  final _textCtrl = TextEditingController();
  final _focusNode = FocusNode();

  // Cevapla / Alıntı modu
  _Alinti? _cevapModu; // null = normal giriş

  bool _gonderiyor = false;

  // Stream bir kez oluşturulur — her build'de yeniden oluşturmayız
  late final Stream<QuerySnapshot> _sohbetStream;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    _sohbetStream = FirebaseFirestore.instance
        .collection('hisseler')
        .doc(widget.symbol)
        .collection('sohbet')
        .orderBy('tarih', descending: true)
        .snapshots();
  }

  @override
  void dispose() {
    _textCtrl.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  CollectionReference get _col => FirebaseFirestore.instance
      .collection('hisseler')
      .doc(widget.symbol)
      .collection('sohbet');

  // ── Mesaj gönder ─────────────────────────────────────────────────────────

  Future<void> _gonder() async {
    final metin = _textCtrl.text.trim();
    if (metin.isEmpty || _gonderiyor) return;

    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    setState(() => _gonderiyor = true);

    final Map<String, dynamic> data = {
      'uid': user.uid,
      'displayName': user.displayName ?? 'Anonim',
      'mesaj': metin,
      'tarih': FieldValue.serverTimestamp(),
      'begeniler': <String>[],
      'begenmeyenler': <String>[],
    };

    if (_cevapModu != null) {
      data['alinti'] = _cevapModu!.toMap();
    }

    try {
      await _col.add(data);
      _textCtrl.clear();
      setState(() {
        _cevapModu = null;
        _gonderiyor = false;
      });
    } catch (_) {
      if (mounted) setState(() => _gonderiyor = false);
    }
  }

  // ── Beğen / Beğenme ───────────────────────────────────────────────────────

  Future<void> _oy(String mesajId, bool begen, List begeniler,
      List begenmeyenler) async {
    final uid = FirebaseAuth.instance.currentUser?.uid;
    if (uid == null) return;

    final ref = _col.doc(mesajId);

    if (begen) {
      if (begeniler.contains(uid)) {
        await ref.update({
          'begeniler': FieldValue.arrayRemove([uid])
        });
      } else {
        await ref.update({
          'begeniler': FieldValue.arrayUnion([uid]),
          'begenmeyenler': FieldValue.arrayRemove([uid]),
        });
      }
    } else {
      if (begenmeyenler.contains(uid)) {
        await ref.update({
          'begenmeyenler': FieldValue.arrayRemove([uid])
        });
      } else {
        await ref.update({
          'begenmeyenler': FieldValue.arrayUnion([uid]),
          'begeniler': FieldValue.arrayRemove([uid]),
        });
      }
    }
  }

  // ── Alıntı / Cevapla modu aç ─────────────────────────────────────────────

  void _cevapla(String mesajId, String mesaj, String displayName) {
    setState(() {
      _cevapModu = _Alinti(
          mesajId: mesajId, mesaj: mesaj, displayName: displayName);
    });
    _focusNode.requestFocus();
  }

  void _alintila(String mesajId, String mesaj, String displayName) {
    // Alıntı = cevap ile aynı yapı, sadece ikon farkı — Firestore'da aynı alan
    _cevapla(mesajId, mesaj, displayName);
  }

  // ── Mesaj sil ────────────────────────────────────────────────────────────

  Future<void> _sil(String mesajId) async {
    final onay = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
        title: const Text('Mesajı Sil',
            style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
        content: const Text('Bu mesaj kalıcı olarak silinecek. Emin misin?',
            style: TextStyle(fontSize: 14)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Vazgeç',
                style: TextStyle(color: Colors.grey)),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Sil', style: TextStyle(fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
    if (onay == true) {
      await _col.doc(mesajId).delete();
    }
  }

  // ── Tarih formatı ─────────────────────────────────────────────────────────

  String _tarihFormat(Timestamp? ts) {
    if (ts == null) return '';
    final dt = ts.toDate().toLocal();
    final simdi = DateTime.now();
    if (dt.year == simdi.year &&
        dt.month == simdi.month &&
        dt.day == simdi.day) {
      return DateFormat('HH:mm', 'tr').format(dt);
    }
    return DateFormat('dd.MM HH:mm', 'tr').format(dt);
  }

  // ── Avatar rengi (displayName'e göre sabit) ───────────────────────────────

  Color _avatarRenk(String name) {
    const renkler = [
      Color(0xFF00C853),
      Color(0xFF2979FF),
      Color(0xFFFF6D00),
      Color(0xFFAA00FF),
      Color(0xFF00BCD4),
      Color(0xFFE91E63),
    ];
    if (name.isEmpty) return renkler[0];
    return renkler[name.codeUnits.first % renkler.length];
  }

  // ─────────────────────────────────────────────────────────────────────────
  //  BUILD
  // ─────────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final mevcutUid = FirebaseAuth.instance.currentUser?.uid ?? '';

    return Column(
      children: [
        // ── Mesaj Listesi ──────────────────────────────────────────────────
        Expanded(
          child: StreamBuilder<QuerySnapshot>(
            stream: _sohbetStream,
            builder: (context, snap) {
              if (snap.connectionState == ConnectionState.waiting) {
                return Center(
                  child: CircularProgressIndicator(
                      color: Theme.of(context).colorScheme.primary),
                );
              }

              final docs = snap.data?.docs ?? [];

              if (docs.isEmpty) {
                return Center(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.chat_bubble_outline,
                          size: 56, color: Theme.of(context).colorScheme.onSurfaceVariant),
                      const SizedBox(height: 12),
                      Text(
                        'Henüz mesaj yok.\nİlk mesajı sen gönder!',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.onSurfaceVariant,
                            fontSize: 14),
                      ),
                    ],
                  ),
                );
              }

              return ListView.builder(
                reverse: true,
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                itemCount: docs.length,
                itemBuilder: (ctx, i) {
                  final doc = docs[i];
                  final d = doc.data() as Map<String, dynamic>;
                  final uid = d['uid'] as String? ?? '';
                  final benimMesajim = uid == mevcutUid;
                  final displayName = d['displayName'] as String? ?? 'Anonim';
                  final mesaj = d['mesaj'] as String? ?? '';
                  final tarih = d['tarih'] as Timestamp?;
                  final begeniler =
                      List<String>.from(d['begeniler'] ?? []);
                  final begenmeyenler =
                      List<String>.from(d['begenmeyenler'] ?? []);
                  final alintiMap = d['alinti'] as Map<String, dynamic>?;
                  final alinti =
                      alintiMap != null ? _Alinti.fromMap(alintiMap) : null;

                  final begendim = begeniler.contains(mevcutUid);
                  final begenmedim = begenmeyenler.contains(mevcutUid);

                  return _MesajKabarcigi(
                    key: ValueKey(doc.id),
                    mesajId: doc.id,
                    displayName: displayName,
                    mesaj: mesaj,
                    tarih: _tarihFormat(tarih),
                    benimMesajim: benimMesajim,
                    begeniler: begeniler.length,
                    begenmeyenler: begenmeyenler.length,
                    begendim: begendim,
                    begenmedim: begenmedim,
                    alinti: alinti,
                    avatarRenk: _avatarRenk(displayName),
                    onBegen: () => _oy(doc.id, true, begeniler, begenmeyenler),
                    onBegenme: () =>
                        _oy(doc.id, false, begeniler, begenmeyenler),
                    onCevapla: () => _cevapla(doc.id, mesaj, displayName),
                    onAlinti: () => _alintila(doc.id, mesaj, displayName),
                    onSil: () => _sil(doc.id),
                  );
                },
              );
            },
          ),
        ),

        // ── Giriş Alanı ───────────────────────────────────────────────────
        _GirisAlani(
          textCtrl: _textCtrl,
          focusNode: _focusNode,
          gonderiyor: _gonderiyor,
          cevapModu: _cevapModu,
          onIptal: () => setState(() => _cevapModu = null),
          onGonder: _gonder,
        ),
      ],
    );
  }
}

// ─── Mesaj Kabarcığı ─────────────────────────────────────────────────────────

class _MesajKabarcigi extends StatelessWidget {
  final String mesajId;
  final String displayName;
  final String mesaj;
  final String tarih;
  final bool benimMesajim;
  final int begeniler;
  final int begenmeyenler;
  final bool begendim;
  final bool begenmedim;
  final _Alinti? alinti;
  final Color avatarRenk;
  final VoidCallback onBegen;
  final VoidCallback onBegenme;
  final VoidCallback onCevapla;
  final VoidCallback onAlinti;
  final VoidCallback onSil;

  // Kendi mesaj balonunun arka plan rengi — yumuşak filigran yeşil
  static const Color _benimRenk = Color(0xFFD6F0DC);

  const _MesajKabarcigi({
    super.key,
    required this.mesajId,
    required this.displayName,
    required this.mesaj,
    required this.tarih,
    required this.benimMesajim,
    required this.begeniler,
    required this.begenmeyenler,
    required this.begendim,
    required this.begenmedim,
    this.alinti,
    required this.avatarRenk,
    required this.onBegen,
    required this.onBegenme,
    required this.onCevapla,
    required this.onAlinti,
    required this.onSil,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment:
            benimMesajim ? MainAxisAlignment.end : MainAxisAlignment.start,
        children: [
          // Avatar (sadece başkasının mesajlarında)
          if (!benimMesajim) ...[
            CircleAvatar(
              radius: 16,
              backgroundColor: avatarRenk,
              child: Text(
                displayName.isNotEmpty ? displayName[0].toUpperCase() : 'A',
                style: const TextStyle(
                    color: Colors.white,
                    fontSize: 13,
                    fontWeight: FontWeight.bold),
              ),
            ),
            const SizedBox(width: 8),
          ],

          Flexible(
            child: Column(
              crossAxisAlignment: benimMesajim
                  ? CrossAxisAlignment.end
                  : CrossAxisAlignment.start,
              children: [
                // İsim + Zaman
                if (!benimMesajim)
                  Padding(
                    padding: const EdgeInsets.only(left: 2, bottom: 3),
                    child: Text(
                      displayName,
                      style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          color: avatarRenk),
                    ),
                  ),

                // Kabarcık
                Container(
                  constraints: BoxConstraints(
                    maxWidth: MediaQuery.of(context).size.width * 0.75,
                  ),
                  decoration: BoxDecoration(
                    color: benimMesajim
                        ? _benimRenk
                        : Theme.of(context).colorScheme.surface,
                    borderRadius: BorderRadius.only(
                      topLeft: const Radius.circular(16),
                      topRight: const Radius.circular(16),
                      bottomLeft: benimMesajim
                          ? const Radius.circular(16)
                          : const Radius.circular(4),
                      bottomRight: benimMesajim
                          ? const Radius.circular(4)
                          : const Radius.circular(16),
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.06),
                        blurRadius: 4,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Alıntı önizleme
                      if (alinti != null)
                        Container(
                          margin: const EdgeInsets.only(bottom: 6),
                          padding: const EdgeInsets.fromLTRB(8, 5, 8, 5),
                          decoration: BoxDecoration(
                            color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.08),
                            borderRadius: BorderRadius.circular(8),
                            border: Border(
                              left: BorderSide(
                                color: Theme.of(context).colorScheme.primary,
                                width: 3,
                              ),
                            ),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                alinti!.displayName,
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  color: Theme.of(context).colorScheme.primary,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                alinti!.mesaj,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: Colors.black54,
                                ),
                              ),
                            ],
                          ),
                        ),

                      // Mesaj metni
                      Text(
                        mesaj,
                        style: TextStyle(
                          fontSize: 14,
                          height: 1.4,
                          color: Theme.of(context).colorScheme.onSurface,
                        ),
                      ),

                      // Zaman
                      const SizedBox(height: 4),
                      Align(
                        alignment: Alignment.bottomRight,
                        child: Text(
                          tarih,
                          style: const TextStyle(
                            fontSize: 10,
                            color: Colors.black45,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),

                // ── Aksiyon İkonları ─────────────────────────────────────
                Padding(
                  padding: const EdgeInsets.only(top: 3, left: 2, right: 2),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _AksiyonDugme(
                        icon: Icons.reply_rounded,
                        label: 'Cevapla',
                        aktif: false,
                        renk: Theme.of(context).colorScheme.onSurfaceVariant,
                        onTap: onCevapla,
                      ),
                      const SizedBox(width: 4),
                      _AksiyonDugme(
                        icon: Icons.format_quote_rounded,
                        label: 'Alıntı',
                        aktif: false,
                        renk: Theme.of(context).colorScheme.onSurfaceVariant,
                        onTap: onAlinti,
                      ),
                      const SizedBox(width: 4),
                      _AksiyonDugme(
                        icon: begenmedim
                            ? Icons.thumb_down
                            : Icons.thumb_down_outlined,
                        label: begenmeyenler > 0 ? '$begenmeyenler' : '',
                        aktif: begenmedim,
                        renk: begenmedim
                            ? Colors.red
                            : Theme.of(context).colorScheme.onSurfaceVariant,
                        onTap: onBegenme,
                      ),
                      const SizedBox(width: 4),
                      _AksiyonDugme(
                        icon: begendim
                            ? Icons.thumb_up
                            : Icons.thumb_up_outlined,
                        label: begeniler > 0 ? '$begeniler' : '',
                        aktif: begendim,
                        renk: begendim
                            ? Theme.of(context).colorScheme.primary
                            : Theme.of(context).colorScheme.onSurfaceVariant,
                        onTap: onBegen,
                      ),
                      if (benimMesajim) ...[
                        const SizedBox(width: 4),
                        _AksiyonDugme(
                          icon: Icons.delete_outline_rounded,
                          label: '',
                          aktif: false,
                          renk: Colors.red.shade300,
                          onTap: onSil,
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),

          // Sağda boşluk (kendi mesajlarımızda avatar yok ama hizalama için)
          if (benimMesajim) const SizedBox(width: 4),
        ],
      ),
    );
  }
}

// ─── Aksiyon Düğmesi ─────────────────────────────────────────────────────────

class _AksiyonDugme extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool aktif;
  final Color renk;
  final VoidCallback onTap;

  const _AksiyonDugme({
    required this.icon,
    required this.label,
    required this.aktif,
    required this.renk,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
        decoration: BoxDecoration(
          color: aktif ? renk.withValues(alpha: 0.1) : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 15, color: renk),
            if (label.isNotEmpty) ...[
              const SizedBox(width: 3),
              Text(
                label,
                style: TextStyle(
                    fontSize: 11,
                    color: renk,
                    fontWeight:
                        aktif ? FontWeight.bold : FontWeight.normal),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

// ─── Giriş Alanı ─────────────────────────────────────────────────────────────

class _GirisAlani extends StatelessWidget {
  final TextEditingController textCtrl;
  final FocusNode focusNode;
  final bool gonderiyor;
  final _Alinti? cevapModu;
  final VoidCallback onIptal;
  final VoidCallback onGonder;

  const _GirisAlani({
    required this.textCtrl,
    required this.focusNode,
    required this.gonderiyor,
    required this.cevapModu,
    required this.onIptal,
    required this.onGonder,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 8,
            offset: const Offset(0, -2),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
            // Cevap/Alıntı önizleme bandı
            if (cevapModu != null)
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                decoration: BoxDecoration(
                  color: const Color(0xFFF0FFF4),
                  border: Border(
                    top: BorderSide(
                        color: Theme.of(context).colorScheme.primary, width: 1),
                    left: BorderSide(
                        color: Theme.of(context).colorScheme.primary, width: 3),
                  ),
                ),
                child: Row(
                  children: [
                    Icon(Icons.reply_rounded,
                        size: 14, color: Theme.of(context).colorScheme.primary),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            cevapModu!.displayName,
                            style: TextStyle(
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                              color: Theme.of(context).colorScheme.primary,
                            ),
                          ),
                          Text(
                            cevapModu!.mesaj,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                                fontSize: 11, color: Colors.black54),
                          ),
                        ],
                      ),
                    ),
                    GestureDetector(
                      onTap: onIptal,
                      child: Icon(Icons.close,
                          size: 16,
                          color: Theme.of(context).colorScheme.onSurfaceVariant),
                    ),
                  ],
                ),
              ),

            // Mesaj giriş satırı
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: Container(
                      decoration: BoxDecoration(
                        color: Theme.of(context).scaffoldBackgroundColor,
                        borderRadius: BorderRadius.circular(24),
                      ),
                      child: TextField(
                        controller: textCtrl,
                        focusNode: focusNode,
                        maxLines: 4,
                        minLines: 1,
                        textCapitalization: TextCapitalization.sentences,
                        style: const TextStyle(fontSize: 14),
                        decoration: InputDecoration(
                          hintText: 'Bir şeyler yaz...',
                          hintStyle: TextStyle(
                              color: Theme.of(context).colorScheme.onSurfaceVariant,
                              fontSize: 14),
                          border: InputBorder.none,
                          contentPadding: const EdgeInsets.symmetric(
                              horizontal: 16, vertical: 10),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  GestureDetector(
                    onTap: onGonder,
                    child: AnimatedContainer(
                      duration: const Duration(milliseconds: 150),
                      width: 44,
                      height: 44,
                      decoration: BoxDecoration(
                        color: Theme.of(context).colorScheme.primary,
                        shape: BoxShape.circle,
                        boxShadow: [
                          BoxShadow(
                            color: Theme.of(context)
                                .colorScheme
                                .primary
                                .withValues(alpha: 0.35),
                            blurRadius: 8,
                            offset: const Offset(0, 2),
                          ),
                        ],
                      ),
                      child: gonderiyor
                          ? const Padding(
                              padding: EdgeInsets.all(12),
                              child: CircularProgressIndicator(
                                  strokeWidth: 2, color: Colors.white),
                            )
                          : const Icon(Icons.send_rounded,
                              color: Colors.white, size: 20),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
    );
  }
}
