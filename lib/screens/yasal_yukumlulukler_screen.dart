import 'package:flutter/material.dart';
import '../models/sozlesme_model.dart';
import '../services/sozlesme_service.dart';
import 'sozlesme_detay_screen.dart';

class YasalYukumluluklerScreen extends StatelessWidget {
  const YasalYukumluluklerScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Yasal Yükümlülükler'),
      ),
      body: ListView(
        children: [
          ListTile(
            title: Text(
              'Sözleşmeler',
              style: TextStyle(
                fontSize: 16,
                color: colorScheme.onSurface,
              ),
            ),
            trailing: Icon(
              Icons.chevron_right_rounded,
              color: colorScheme.onSurfaceVariant,
            ),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => const SozlesmelerListeScreen(),
              ),
            ),
          ),
          Divider(height: 1, color: colorScheme.outlineVariant),
          ListTile(
            title: Text(
              'Onay Bekleyenler',
              style: TextStyle(
                fontSize: 16,
                color: colorScheme.onSurface,
              ),
            ),
            trailing: Icon(
              Icons.chevron_right_rounded,
              color: colorScheme.onSurfaceVariant,
            ),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => const OnayBekleyenlerScreen(),
              ),
            ),
          ),
          Divider(height: 1, color: colorScheme.outlineVariant),
        ],
      ),
    );
  }
}

class SozlesmelerListeScreen extends StatelessWidget {
  const SozlesmelerListeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Sözleşmeler'),
      ),
      body: FutureBuilder<List<SozlesmeUiModel>>(
        future: SozlesmeService.instance.sozlesmeUiModelleriniGetir(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return Center(
              child: CircularProgressIndicator(color: colorScheme.primary),
            );
          }

          if (snapshot.hasError) {
            return Center(
              child: Text(
                'Sözleşmeler yüklenemedi.',
                style: TextStyle(color: colorScheme.error),
              ),
            );
          }

          final models = snapshot.data ?? [];

          if (models.isEmpty) {
            return Center(
              child: Text(
                'Sözleşme bulunamadı.',
                style: TextStyle(color: colorScheme.onSurfaceVariant),
              ),
            );
          }

          return ListView.separated(
            itemCount: models.length,
            separatorBuilder: (_, _) =>
                Divider(height: 1, color: colorScheme.outlineVariant),
            itemBuilder: (context, index) {
              final model = models[index];
              return ListTile(
                title: Text(
                  model.definition.baslik,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: model.onaylandi
                        ? FontWeight.normal
                        : FontWeight.bold,
                    color: colorScheme.primary,
                  ),
                ),
                trailing: Icon(
                  Icons.chevron_right_rounded,
                  color: colorScheme.onSurfaceVariant,
                ),
                onTap: () => Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => SozlesmeDetayScreen(
                      definition: model.definition,
                      onayKaydi: model.onayKaydi,
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

class OnayBekleyenlerScreen extends StatefulWidget {
  const OnayBekleyenlerScreen({super.key});

  @override
  State<OnayBekleyenlerScreen> createState() => _OnayBekleyenlerScreenState();
}

class _OnayBekleyenlerScreenState extends State<OnayBekleyenlerScreen> {
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
        title: const Text('Onay Bekleyenler'),
      ),
      body: FutureBuilder<List<SozlesmeUiModel>>(
        future: _future,
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return Center(
              child: CircularProgressIndicator(color: colorScheme.primary),
            );
          }

          final tumModels = snapshot.data ?? [];
          final bekleyenler =
              tumModels.where((m) => !m.onaylandi).toList();

          if (bekleyenler.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(
                    Icons.check_circle_outline_rounded,
                    size: 56,
                    color: colorScheme.primary,
                  ),
                  const SizedBox(height: 16),
                  Text(
                    'Tüm sözleşmeler onaylandı.',
                    style: TextStyle(
                      fontSize: 16,
                      color: colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            );
          }

          final hepsiokundu =
              bekleyenler.every((m) => m.okundu);
          final hepsitiklendi = bekleyenler
              .every((m) => _tikliIds.contains(m.definition.id));
          final kabulAktif = hepsiokundu && hepsitiklendi;

          return Column(
            children: [
              Expanded(
                child: ListView.separated(
                  itemCount: bekleyenler.length,
                  separatorBuilder: (_, _) =>
                      Divider(height: 1, color: colorScheme.outlineVariant),
                  itemBuilder: (context, index) {
                    final model = bekleyenler[index];
                    final tikli =
                        _tikliIds.contains(model.definition.id);

                    return _OnayBekleyenSatir(
                      model: model,
                      tikli: tikli,
                      onTikDegisti: model.okundu
                          ? (value) {
                              setState(() {
                                if (value == true) {
                                  _tikliIds.add(model.definition.id);
                                } else {
                                  _tikliIds
                                      .remove(model.definition.id);
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
                            .sozlesmeOkunduIsaretle(
                                model.definition.id);
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
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: kabulAktif
                        ? () async {
                            final tikliDefinitions = bekleyenler
                                .where((m) => _tikliIds
                                    .contains(m.definition.id))
                                .map((m) => m.definition)
                                .toList();
                            await SozlesmeService.instance
                                .topluOnayla(
                              definitions: tikliDefinitions,
                            );
                            if (mounted) {
                              setState(() {
                                _tikliIds.clear();
                                _yenile();
                              });
                            }
                          }
                        : null,
                    style: FilledButton.styleFrom(
                      backgroundColor: colorScheme.primary,
                      foregroundColor: colorScheme.onPrimary,
                      disabledBackgroundColor:
                          colorScheme.onSurface.withValues(alpha: 0.38),
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
              ),
            ],
          );
        },
      ),
    );
  }
}

class _OnayBekleyenSatir extends StatelessWidget {
  final SozlesmeUiModel model;
  final bool tikli;
  final ValueChanged<bool?>? onTikDegisti;
  final VoidCallback onDetayGit;

  const _OnayBekleyenSatir({
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
                return colorScheme.onSurface.withValues(alpha: 0.38);
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