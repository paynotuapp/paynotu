import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';

class OnurListesiScreen extends StatelessWidget {
  const OnurListesiScreen({super.key});

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
          '🏆 Onur Listesi',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
        ),
      ),
      body: StreamBuilder<QuerySnapshot>(
        stream: FirebaseFirestore.instance
            .collection('onur_listesi')
            .snapshots(),
        builder: (ctx, snap) {
          if (snap.connectionState == ConnectionState.waiting) {
            return Center(
              child: CircularProgressIndicator(
                color: Theme.of(ctx).colorScheme.primary,
              ),
            );
          }

          final docs = snap.data?.docs ?? [];

          if (docs.isEmpty) {
            return Center(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(Icons.coffee,
                      size: 64,
                      color: Theme.of(ctx).colorScheme.onSurfaceVariant),
                  const SizedBox(height: 12),
                  Text(
                    'Henüz bağışçı yok.',
                    style: TextStyle(
                        color: Theme.of(ctx).colorScheme.onSurfaceVariant,
                        fontSize: 15),
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'İlk destekçi sen ol! ☕',
                    style: TextStyle(
                        color: Theme.of(ctx).colorScheme.onSurfaceVariant,
                        fontSize: 13),
                  ),
                ],
              ),
            );
          }

          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: docs.length,
            separatorBuilder: (_, i) => const SizedBox(height: 8),
            itemBuilder: (ctx2, i) {
              final data = docs[i].data() as Map<String, dynamic>;
              final isim = data['ad'] ?? 'İsimsiz';

              return Container(
                decoration: BoxDecoration(
                  color: Theme.of(ctx2).colorScheme.surface,
                  borderRadius: BorderRadius.circular(12),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.04),
                      blurRadius: 4,
                      offset: const Offset(0, 2),
                    ),
                  ],
                ),
                child: ListTile(
                  leading: CircleAvatar(
                    backgroundColor: i == 0
                        ? const Color(0xFFFFD700).withValues(alpha: 0.15)
                        : Theme.of(ctx2)
                            .colorScheme
                            .primary
                            .withValues(alpha: 0.1),
                    child: Text(
                      i == 0
                          ? '🥇'
                          : i == 1
                              ? '🥈'
                              : i == 2
                                  ? '🥉'
                                  : '☕',
                      style: const TextStyle(fontSize: 18),
                    ),
                  ),
                  title: Text(
                    '$isim ☕',
                    style: const TextStyle(
                        fontWeight: FontWeight.w600, fontSize: 14),
                  ),
                  trailing: i == 0
                      ? Container(
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 4),
                          decoration: BoxDecoration(
                            color: const Color(0xFFFFD700)
                                .withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: const Text(
                            'İlk Destekçi',
                            style: TextStyle(
                              fontSize: 10,
                              color: Color(0xFFB8860B),
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        )
                      : null,
                ),
              );
            },
          );
        },
      ),
    );
  }
}