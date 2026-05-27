import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';
import '../models/sozlesme_model.dart';
import '../services/sozlesme_service.dart';

class SozlesmeDetayScreen extends StatefulWidget {
  final SozlesmeDefinition definition;
  final SozlesmeOnayKaydi? onayKaydi;

  const SozlesmeDetayScreen({
    super.key,
    required this.definition,
    this.onayKaydi,
  });

  @override
  State<SozlesmeDetayScreen> createState() => _SozlesmeDetayScreenState();
}

class _SozlesmeDetayScreenState extends State<SozlesmeDetayScreen> {
  @override
  void initState() {
    super.initState();
    SozlesmeService.instance
        .sozlesmeOkunduIsaretle(widget.definition.id);
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final tarihFormat = DateFormat('dd/MM/yyyy');

    final gosterilecekTarih = widget.onayKaydi != null
        ? tarihFormat.format(widget.onayKaydi!.onayTarihi)
        : tarihFormat.format(widget.definition.yayinTarihi);

    final gosterilecekKanal = widget.onayKaydi != null
        ? widget.onayKaydi!.kanal.label
        : 'Mobil Uygulama';

    return Scaffold(
      appBar: AppBar(
        title: const Text('Sözleşme Bilgileri'),
      ),
      floatingActionButton: FloatingActionButton(
        onPressed: () => _pdfAc(context),
        backgroundColor: colorScheme.primary,
        foregroundColor: colorScheme.onPrimary,
        tooltip: 'PDF Görüntüle',
        child: const Icon(Icons.picture_as_pdf_rounded),
      ),
      body: ListView(
        children: [
          _InfoSatiri(
            etiket: 'Belge Adı',
            deger: widget.definition.baslik,
          ),
          Divider(height: 1, color: colorScheme.outlineVariant),
          _InfoSatiri(
            etiket: 'Belge Tarihi',
            deger: gosterilecekTarih,
          ),
          Divider(height: 1, color: colorScheme.outlineVariant),
          _InfoSatiri(
            etiket: 'Onaylama Kanalı',
            deger: gosterilecekKanal,
          ),
          Divider(height: 1, color: colorScheme.outlineVariant),
        ],
      ),
    );
  }

  void _pdfAc(BuildContext context) async {
    final url = widget.definition.icerikUrl;
    if (url.startsWith('http')) {
      final uri = Uri.parse(url);
      if (await canLaunchUrl(uri)) {
        await launchUrl(
          uri,
          mode: LaunchMode.externalApplication,
        );
      } else {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: const Text('PDF açılamadı.'),
              backgroundColor:
                  Theme.of(context).colorScheme.inverseSurface,
            ),
          );
        }
      }
    } else {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('PDF bağlantısı tanımlanmamış.'),
            backgroundColor:
                Theme.of(context).colorScheme.inverseSurface,
          ),
        );
      }
    }
  }
}

class _InfoSatiri extends StatelessWidget {
  final String etiket;
  final String deger;

  const _InfoSatiri({
    required this.etiket,
    required this.deger,
  });

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            etiket,
            style: TextStyle(
              fontSize: 14,
              color: colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(width: 24),
          Flexible(
            child: Text(
              deger,
              textAlign: TextAlign.end,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: colorScheme.onSurface,
              ),
            ),
          ),
        ],
      ),
    );
  }
}