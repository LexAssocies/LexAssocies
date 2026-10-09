-- Accès public en lecture pour les visuels du site.
create policy "public may view site assets"
on storage.objects for select
using (bucket_id in ('site-assets', 'book-covers'));

-- Les utilisateurs connectés peuvent déposer des supports ; les suppressions
-- restent réservées à une future règle d'administration côté serveur.
create policy "authenticated may upload files"
on storage.objects for insert to authenticated
with check (bucket_id in ('site-assets', 'book-covers', 'course-files', 'downloads'));
