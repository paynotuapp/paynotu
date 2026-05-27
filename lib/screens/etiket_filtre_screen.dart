import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:pay/screens/paynotu_puan_screen.dart';

class EtiketFiltreScreen extends StatelessWidget {
  /// filtreTip: 'sector' | 'industry' | 'pazar' | 'endeks'
  final String filtreTip;
  final String filtreValue;
  final String baslik;
  final Color renk;

  const EtiketFiltreScreen({
    super.key,
    required this.filtreTip,
    required this.filtreValue,
    required this.baslik,
    required this.renk,
  });

  Query _query() {
    final col = FirebaseFirestore.instance
        .collection('hisseler')
        .where('kap_aktif', isEqualTo: true);
    switch (filtreTip) {
      case 'endeks':
        return col.where('endeksler', arrayContains: filtreValue);
      case 'pazar':
        return col.where('pazar', isEqualTo: filtreValue);
      case 'sector':
        return col.where('sector', isEqualTo: filtreValue);
      case 'industry':
      default:
        return col.where('industry', isEqualTo: filtreValue);
    }
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
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              filtreValue,
              style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                  fontSize: 16),
            ),
            Text(
              baslik,
              style: const TextStyle(
                  color: Colors.white70,
                  fontSize: 11),
            ),
          ],
        ),
      ),
      body: StreamBuilder<QuerySnapshot>(
        stream: _query().snapshots(),
        builder: (context, snapshot) {
          if (snapshot.connectionState == ConnectionState.waiting) {
            return Center(
              child: CircularProgressIndicator(color: Theme.of(context).colorScheme.primary),
            );
          }
          if (snapshot.hasError) {
            return Center(child: Text('Hata: ${snapshot.error}'));
          }

          final docs = snapshot.data?.docs ?? [];

          if (docs.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.label_off_outlined, size: 64, color: renk.withValues(alpha: 0.4)),
                  const SizedBox(height: 12),
                  Text(
                    '"$filtreValue" etiketinde hisse bulunamadı.',
                    style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 14),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            );
          }

          return Column(
            children: [
              Container(
                color: Theme.of(context).colorScheme.surface,
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                child: Row(
                  children: [
                    Flexible(
                      child: Container(
                        constraints: const BoxConstraints(maxWidth: 240),
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: renk.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(20),
                          border: Border.all(color: renk.withValues(alpha: 0.3)),
                        ),
                        child: Text(
                          filtreValue,
                          maxLines: 1,
                          softWrap: false,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                              fontSize: 12,
                              color: renk,
                              fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                    const Spacer(),
                    Text(
                      '${docs.length} hisse',
                      style: TextStyle(
                          fontSize: 12,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                          fontWeight: FontWeight.w500),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView.builder(
                  itemCount: docs.length,
                  itemBuilder: (context, index) {
                    final data = docs[index].data() as Map<String, dynamic>;
                    return HisseKarti(data: data);
                  },
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}
