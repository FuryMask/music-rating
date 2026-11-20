-- Run in a disposable PostgreSQL database with Supabase auth/storage schemas.
begin;

insert into auth.users(id) values
    ('aaaaaaaa-0000-0000-0000-000000000001'),
    ('bbbbbbbb-0000-0000-0000-000000000002');

create policy test_permissive_storage_policy on storage.objects
    for all to authenticated using (true) with check (true);

set local role authenticated;
select set_config('request.jwt.claim.sub', 'aaaaaaaa-0000-0000-0000-000000000001', true);
select public.music_rating_upload(jsonb_build_array(jsonb_build_object(
    'kind', 'album', 'item_id', 'a1', 'snapshot_hash', repeat('a', 64), 'payload', jsonb_build_object('title', 'First')
)));
select public.music_rating_upload(jsonb_build_array(jsonb_build_object(
    'kind', 'album', 'item_id', 'a1', 'snapshot_hash', repeat('b', 64), 'payload', jsonb_build_object('title', 'Update')
)));
insert into storage.objects(bucket_id, name) values
    ('music-rating-artwork', 'aaaaaaaa-0000-0000-0000-000000000001/test-image');

do $$
begin
    if (select count(*) from public.music_rating_library) <> 1
        or not exists(select from public.music_rating_library where payload->>'title' = 'Update') then
        raise exception 'Retry did not update exactly one record';
    end if;
end $$;

select set_config('request.jwt.claim.sub', 'bbbbbbbb-0000-0000-0000-000000000002', true);
do $$
begin
    if exists(select from public.music_rating_library) or exists(select from storage.objects) then
        raise exception 'Another account can read private data';
    end if;
    begin
        insert into public.music_rating_library (owner_id, kind, item_id, snapshot_hash, payload)
        values ('aaaaaaaa-0000-0000-0000-000000000001', 'rating', 'forged', repeat('c', 64), '{}');
        raise exception 'Another account wrote a forged record';
    exception when insufficient_privilege then null;
    end;
    begin
        insert into storage.objects(bucket_id, name)
        values ('music-rating-artwork', 'aaaaaaaa-0000-0000-0000-000000000001/other-image');
        raise exception 'Another account uploaded artwork to a foreign namespace';
    exception when insufficient_privilege then null;
    end;
end $$;
select public.music_rating_upload(jsonb_build_array(jsonb_build_object(
    'kind', 'album', 'item_id', 'a1', 'snapshot_hash', repeat('c', 64), 'payload', jsonb_build_object('title', 'Other')
)));
do $$
begin
    if (select count(*) from public.music_rating_library) <> 1
        or not exists(select from public.music_rating_library where payload->>'title' = 'Other') then
        raise exception 'Owners sharing a local ID did not receive independent records';
    end if;
    if has_function_privilege('anon', 'public.music_rating_upload(jsonb)', 'execute')
        or has_table_privilege('anon', 'public.music_rating_library', 'select') then
        raise exception 'Anonymous access is unexpectedly available';
    end if;
end $$;

rollback;
