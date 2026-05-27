import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:html/parser.dart' as html_parser;

class TemettuTakvimiScreen extends StatefulWidget {
  const TemettuTakvimiScreen({super.key});

  @override
  State<TemettuTakvimiScreen> createState() => _TemettuTakvimiScreenState();
}

class _TemettuTakvimiScreenState extends State<TemettuTakvimiScreen> {
  List<_TemettuSatir> _tumSatirlar = [];
  List<_TemettuSatir> _satirlar = [];
  bool _yukleniyor = true;
  String? _hata;
  final _aramaCtrl = TextEditingController();
  String _arama = '';

  @override
  void initState() {
    super.initState();
    _yukle();
  }

  @override
  void dispose() {
    _aramaCtrl.dispose();
    super.dispose();
  }

  Future<void> _yukle() async {
    setState(() {
      _yukleniyor = true;
      _hata = null;
    });
    try {
      final res = await http.get(
        Uri.parse('https://www.getmidas.com/temettu-takvim/'),
        headers: {
          'User-Agent':
              'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
          'Accept': 'text/html',
        },
      ).timeout(const Duration(seconds: 15));

      if (res.statusCode != 200) {
        throw Exception('Sunucu yanıt vermedi (HTTP ${res.statusCode})');
      }

      final doc = html_parser.parse(res.body);
      final rows =
          doc.querySelectorAll('table.stock-table tbody tr.table-row');

      if (rows.isEmpty) {
        throw Exception('Tablo bulunamadı. Sayfa yapısı değişmiş olabilir.');
      }

      final list = <_TemettuSatir>[];
      for (final row in rows) {
        final cells = row.querySelectorAll('td');
        if (cells.length < 4) continue;
        final kod =
            cells[0].querySelector('a')?.text.trim() ?? cells[0].text.trim();
        final tarih = cells[1].text.trim();
        final toplam = cells[2].text.trim();
        final hisseBasi = cells[3].text.trim();
        if (kod.isEmpty) continue;
        list.add(_TemettuSatir(
          kod: kod,
          tarih: tarih,
          toplamTemettu: toplam,
          hisseBasiNet: hisseBasi,
        ));
      }

      if (list.isEmpty) throw Exception('Veri parse edilemedi.');

      setState(() {
        _tumSatirlar = list;
        _satirlar = list;
        _yukleniyor = false;
      });
    } catch (e) {
      setState(() {
        _hata = e.toString();
        _yukleniyor = false;
      });
    }
  }

  void _aramaGuncelle(String q) {
    setState(() {
      _arama = q.trim().toUpperCase();
      _satirlar = _arama.isEmpty
          ? _tumSatirlar
          : _tumSatirlar
              .where((s) => s.kod.contains(_arama))
              .toList();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        backgroundColor: Theme.of(context).colorScheme.primary,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back, color: Colors.white),
          onPressed: () => Navigator.pop(context),
        ),
        title: const Text(
          '📅 Temettü Takvimi',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh, color: Colors.white),
            onPressed: _yukle,
          ),
        ],
      ),
      body: _yukleniyor
          ? Center(
              child: CircularProgressIndicator(color: Theme.of(context).colorScheme.primary),
            )
          : _hata != null
              ? _hataWidget()
              : Column(
                  children: [
                    // Liste
                    Expanded(
                      child: RefreshIndicator(
                        color: Theme.of(context).colorScheme.primary,
                        onRefresh: _yukle,
                        child: _satirlar.isEmpty
                            ? Center(
                                child: Text(
                                  '"$_arama" bulunamadı.',
                                  style: TextStyle(
                                      color: Colors.grey.shade500,
                                      fontSize: 14),
                                ),
                              )
                            : ListView.separated(
                                padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
                                itemCount: _satirlar.length,
                                separatorBuilder: (_, i) =>
                                    const SizedBox(height: 8),
                                itemBuilder: (ctx, i) => _kart(_satirlar[i]),
                              ),
                      ),
                    ),
                    // Arama çubuğu (alt)
                    _aramaPanel(),
                  ],
                ),
    );
  }

  Widget _aramaPanel() {
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.08),
            blurRadius: 10,
            offset: const Offset(0, -3),
          ),
        ],
        borderRadius:
            const BorderRadius.vertical(top: Radius.circular(16)),
      ),
      padding: EdgeInsets.fromLTRB(
        16,
        12,
        16,
        12 + MediaQuery.of(context).padding.bottom,
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _aramaCtrl,
              onChanged: _aramaGuncelle,
              textCapitalization: TextCapitalization.characters,
              decoration: InputDecoration(
                hintText: 'Hisse kodu ara... (ör: ALARK)',
                prefixIcon: Icon(Icons.search,
                    color: Theme.of(context).colorScheme.primary, size: 20),
                suffixIcon: _arama.isNotEmpty
                    ? IconButton(
                        icon: const Icon(Icons.clear,
                            size: 18, color: Colors.grey),
                        onPressed: () {
                          _aramaCtrl.clear();
                          _aramaGuncelle('');
                        },
                      )
                    : null,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide:
                      BorderSide(color: Colors.grey.shade300),
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide(
                      color: Theme.of(context).colorScheme.primary, width: 1.5),
                ),
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 12, vertical: 12),
                filled: true,
                fillColor: Theme.of(context).scaffoldBackgroundColor,
              ),
            ),
          ),
          if (_tumSatirlar.isNotEmpty) ...[
            const SizedBox(width: 10),
            Text(
              '${_satirlar.length}/${_tumSatirlar.length}',
              style: TextStyle(
                  fontSize: 12, color: Colors.grey.shade500),
            ),
          ],
        ],
      ),
    );
  }

  Widget _hataWidget() {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off, size: 56, color: Theme.of(context).colorScheme.onSurfaceVariant),
            const SizedBox(height: 12),
            const Text(
              'Temettü takvimi yüklenemedi.',
              style:
                  TextStyle(fontWeight: FontWeight.bold, fontSize: 15),
            ),
            const SizedBox(height: 6),
            Text(
              _hata ?? '',
              style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 12),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 16),
            ElevatedButton.icon(
              onPressed: _yukle,
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('Tekrar Dene'),
              style: ElevatedButton.styleFrom(
                backgroundColor: Theme.of(context).colorScheme.primary,
                foregroundColor: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _kart(_TemettuSatir s) {
    return Container(
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border(
          left: BorderSide(color: Theme.of(context).colorScheme.primary, width: 3),
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.05),
            blurRadius: 4,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Üst satır: hisse kodu + tarih
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(
                    horizontal: 9, vertical: 4),
                decoration: BoxDecoration(
                  color: Theme.of(context).colorScheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  s.kod,
                  style: TextStyle(
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: Theme.of(context).colorScheme.primary,
                  ),
                ),
              ),
              const Spacer(),
              Icon(Icons.calendar_today,
                  size: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
              const SizedBox(width: 4),
              Text(
                s.tarih,
                style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
            ],
          ),
          const SizedBox(height: 8),
          // Alt satır: hisse başı + toplam
          Row(
            children: [
              const Icon(Icons.toll, size: 13, color: Colors.blueGrey),
              const SizedBox(width: 4),
              Expanded(
                flex: 3,
                child: Text(
                  'Hisse Başı Net: ${s.hisseBasiNet}',
                  style: const TextStyle(
                      fontSize: 12, fontWeight: FontWeight.w600),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 6),
              Expanded(
                flex: 2,
                child: Text(
                  s.toplamTemettu,
                  style: TextStyle(
                      fontSize: 11, color: Colors.grey.shade500),
                  textAlign: TextAlign.right,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _TemettuSatir {
  final String kod;
  final String tarih;
  final String toplamTemettu;
  final String hisseBasiNet;

  const _TemettuSatir({
    required this.kod,
    required this.tarih,
    required this.toplamTemettu,
    required this.hisseBasiNet,
  });
}
