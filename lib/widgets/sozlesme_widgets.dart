import 'package:flutter/material.dart';
import '../models/sozlesme_model.dart';
import '../services/sozlesme_service.dart';
import '../screens/sozlesme_detay_screen.dart';
import '../screens/giris_screen.dart';

class IlkOnayScreen extends StatefulWidget {
  final VoidCallback onTamamlandi;

  const IlkOnayScreen({super.key, required this.onTamamlandi});

  @override
  State<IlkOnayScreen> createState() => _IlkOnayScreenState();
}

class _IlkOnayScreenState extends State<IlkOnayScreen> {
  late Future<List<SozlesmeUiModel>> _future;
  final Set<String> _tikliIds = {};

  @override
  void initState() {
    super.initState();
    _yenile();
  }

  void _yenile() {
    _future = SozlesmeService.instance.sozlesmeUiModelleriniGetir();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: const Text('Sözleşmeleri Onayla'),
      ),
      body: FutureBuilder<List<SozlesmeUiModel>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return Center(
              child: CircularProgressIndicator(color: colorScheme.primary),
            );
          }

          final bekleyenler = (snapshot.data ?? [])
              .where((m) => m.bekleyenOnay)
              .toList();

          final hepsitiklendi = bekleyenler.isNotEmpty &&
              bekleyenler.every((m) => _tikliIds.contains(m.definition.id));

          return Column(
            children: [
              Expanded(
                child: ListView.separated(
                  itemCount: bekleyenler.length,
                  separatorBuilder: (_, _) =>
                      Divider(height: 1, color: colorScheme.outlineVariant),
                  itemBuilder: (context, index) {
                    final model = bekleyenler[index];
                    final tikli = _tikliIds.contains(model.definition.id);

                    return _SozlesmeSatir(
                      model: model,
                      tikli: tikli,
                      onTikDegisti: model.okundu
                          ? (value) {
                              setState(() {
                                if (value == true) {
                                  _tikliIds.add(model.definition.id);
                                } else {
                                  _tikliIds.remove(model.definition.id);
                                }
                              });
                            }
                          : null,
                      onDetayGit: () async {
                        await Navigator.push(
                          context,
                          MaterialPageRoute(
                            builder: (_) => SozlesmeDetayScreen(
                              definition: model.definition,
                              onayKaydi: model.onayKaydi,
                            ),
                          ),
                        );
                        SozlesmeService.instance
                            .sozlesmeOkunduIsaretle(model.definition.id);
                        if (mounted) {
                          setState(() => _yenile());
                        }
                      },
                    );
                  },
                ),
              ),
              Container(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
                decoration: BoxDecoration(
                  color: colorScheme.surface,
                  border: Border(
                    top: BorderSide(color: colorScheme.outlineVariant),
                  ),
                ),
                child: Column(
                  children: [
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: hepsitiklendi
                            ? () async {
                                final tikliDefinitions = bekleyenler
                                    .where((m) =>
                                        _tikliIds.contains(m.definition.id))
                                    .map((m) => m.definition)
                                    .toList();
                                await SozlesmeService.instance.topluOnayla(
                                  definitions: tikliDefinitions,
                                );
                                widget.onTamamlandi();
                              }
                            : null,
                        style: FilledButton.styleFrom(
                          backgroundColor: colorScheme.primary,
                          foregroundColor: colorScheme.onPrimary,
                          disabledBackgroundColor:
                              colorScheme.onSurface.withValues(alpha: 0.12),
                          disabledForegroundColor:
                              colorScheme.onSurface.withValues(alpha: 0.38),
                          padding:
                              const EdgeInsets.symmetric(vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                        child: const Text(
                          'Kabul Ediyorum',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    SizedBox(
                      width: double.infinity,
                      child: TextButton(
                        onPressed: () {
                          Navigator.pushAndRemoveUntil(
                            context,
                            MaterialPageRoute(
                                builder: (_) => const GirisScreen()),
                            (route) => false,
                          );
                        },
                        style: TextButton.styleFrom(
                          padding:
                              const EdgeInsets.symmetric(vertical: 14),
                        ),
                        child: Text(
                          'Kabul Etmiyorum',
                          style: TextStyle(
                            fontSize: 15,
                            color: colorScheme.error,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _SozlesmeSatir extends StatelessWidget {
  final SozlesmeUiModel model;
  final bool tikli;
  final ValueChanged<bool?>? onTikDegisti;
  final VoidCallback onDetayGit;

  const _SozlesmeSatir({
    required this.model,
    required this.tikli,
    required this.onTikDegisti,
    required this.onDetayGit,
  });

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final okundu = model.okundu;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          Checkbox(
            value: tikli,
            onChanged: onTikDegisti,
            activeColor: colorScheme.primary,
            fillColor: WidgetStateProperty.resolveWith((states) {
              if (states.contains(WidgetState.disabled)) {
                return colorScheme.onSurface.withValues(alpha: 0.12);
              }
              if (states.contains(WidgetState.selected)) {
                return colorScheme.primary;
              }
              return null;
            }),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(4),
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: GestureDetector(
              onTap: onDetayGit,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    model.definition.baslik,
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.bold,
                      color: colorScheme.primary,
                      decoration: TextDecoration.underline,
                      decorationColor: colorScheme.primary,
                    ),
                  ),
                  if (!okundu) ...[
                    const SizedBox(height: 2),
                    Text(
                      'Onaylamak için önce okuyunuz',
                      style: TextStyle(
                        fontSize: 11,
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(width: 8),
          Icon(
            okundu
                ? Icons.visibility_rounded
                : Icons.visibility_off_outlined,
            size: 18,
            color: okundu
                ? colorScheme.primary
                : colorScheme.onSurfaceVariant,
          ),
        ],
      ),
    );
  }
}
