import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:pay/screens/paynotu_puan_screen.dart';

class TakipScreen extends StatelessWidget {
  const TakipScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final uid = FirebaseAuth.instance.currentUser?.uid;

    if (uid == null) {
      return const Center(
        child: Text('Giriş yapmanız gerekiyor.'),
      );
    }

    final takipQuery = FirebaseFirestore.instance
        .collection('users')
        .doc(uid)
        .collection('takip')
        .orderBy('eklenmeTarihi', descending: true);

    return StreamBuilder<QuerySnapshot>(
      stream: takipQuery.snapshots(),
      builder: (context, takipSnap) {
        if (takipSnap.connectionState == ConnectionState.waiting) {
          return Center(
            child: CircularProgressIndicator(color: Theme.of(context).colorScheme.primary),
          );
        }

        final takipDocs = takipSnap.data?.docs ?? [];

        if (takipDocs.isEmpty) {
          return Center(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.remove_red_eye_outlined, size: 64, color: Theme.of(context).colorScheme.onSurfaceVariant),
                const SizedBox(height: 12),
                Text(
                  'Henüz takip ettiğiniz hisse yok.',
                  style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 15),
                ),
                const SizedBox(height: 6),
                Text(
                  'Hisse listesinde sola kaydırarak takibe alabilirsiniz.',
                  style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant, fontSize: 12),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          );
        }

        final semboller = takipDocs.map((d) => d.id).toList();

        return ListView.builder(
          itemCount: semboller.length,
          itemBuilder: (context, index) {
            final sembol = semboller[index];
            return StreamBuilder<DocumentSnapshot>(
              stream: FirebaseFirestore.instance
                  .collection('hisseler')
                  .doc(sembol)
                  .snapshots(),
              builder: (context, hisseSnap) {
                if (!hisseSnap.hasData) return const SizedBox();
                final data = hisseSnap.data?.data() as Map<String, dynamic>?;
                if (data == null) return const SizedBox();
                if (data['kap_aktif'] == false) return const SizedBox();
                return HisseKarti(data: data);
              },
            );
          },
        );
      },
    );
  }
}
