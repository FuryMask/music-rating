begin;

-- Only the project administrator can grant access or set the displayed name.
create table public.music_rating_members (
    user_id uuid primary key references auth.users(id) on delete cascade,
    display_name text not null check (char_length(btrim(display_name)) between 1 and 80)
);
create unique index music_rating_member_name on public.music_rating_members (lower(btrim(display_name)));

create table public.music_rating_shared (
    kind text not null check (kind in ('album', 'artist', 'rating', 'summary')),
    item_id text not null,
    payload jsonb not null check (jsonb_typeof(payload) = 'object'),
    updated_at timestamptz not null default now(),
    primary key (kind, item_id)
);

create table public.music_rating_shared_revision (
    singleton boolean primary key default true check (singleton),
    revision bigint not null default 0
);
insert into public.music_rating_shared_revision default values;

alter table public.music_rating_members enable row level security;
alter table public.music_rating_shared enable row level security;
alter table public.music_rating_shared_revision enable row level security;
revoke all on public.music_rating_members, public.music_rating_shared,
    public.music_rating_shared_revision from public, anon, authenticated;
grant select on public.music_rating_members to anon, authenticated;
create policy music_rating_member_self on public.music_rating_members
    for select to authenticated using ((select auth.uid()) = user_id);

create function public.music_rating_shared_status(p_download boolean default false) returns jsonb
    language plpgsql stable security definer set search_path = '' as $$
declare
    caller uuid := auth.uid();
    result jsonb;
begin
    if not exists (select 1 from public.music_rating_members where user_id = caller) then
        raise exception using errcode = 'PT403', message = 'MUSIC_RATING_MEMBERSHIP_REQUIRED';
    end if;

    select jsonb_build_object(
        'revision', revision::text || ':' || coalesce((
            select max(updated_at)::text from public.music_rating_library where owner_id = caller
        ), ''),
        'members', (select coalesce(jsonb_agg(jsonb_build_object(
            'id', user_id, 'name', btrim(display_name)) order by lower(display_name)), '[]'::jsonb)
            from public.music_rating_members),
        'has_data', exists (select 1 from public.music_rating_shared)
            or exists (select 1 from public.music_rating_library where owner_id = caller)
    ) into result from public.music_rating_shared_revision;

    if p_download then
        result := result || jsonb_build_object(
            'shared', (select coalesce(jsonb_agg(to_jsonb(row) order by kind, item_id), '[]'::jsonb)
                from public.music_rating_shared row),
            'personal', (select coalesce(jsonb_agg(jsonb_build_object(
                'kind', kind, 'item_id', item_id, 'payload', payload) order by kind, item_id), '[]'::jsonb)
                from public.music_rating_library where owner_id = caller)
        );
    end if;
    return result;
end;
$$;

create function public.music_rating_shared_upload(p_items jsonb) returns void
    language plpgsql security definer set search_path = '' as $$
declare
    changed integer;
begin
    if not exists (select 1 from public.music_rating_members where user_id = auth.uid()) then
        raise exception using errcode = 'PT403', message = 'MUSIC_RATING_MEMBERSHIP_REQUIRED';
    end if;
    if exists (
        select 1 from jsonb_to_recordset(p_items) as item(kind text, item_id text, payload jsonb)
        where kind = 'rating' and (
            (payload->>'album_id' is null or payload->>'rater_key' is null
             or item_id <> (payload->>'album_id') || ':' || (payload->>'rater_key'))
            or jsonb_typeof(payload->'scores') is distinct from 'object'
            or not ((payload->>'rater_key') ~ '^local-[0-9a-f]{64}$' or exists (
                select 1 from public.music_rating_members where user_id::text = payload->>'rater_key'
            ))
            or exists (select 1 from jsonb_each(payload->'scores') as score
                where case when jsonb_typeof(value) = 'number'
                    then (value::text)::numeric not between 0 and 11 else true end)
        )
    ) then
        raise exception using errcode = '22023', message = 'Invalid rating column';
    end if;

    -- Serialize uploads so a later revision always includes all preceding writes.
    perform 1 from public.music_rating_shared_revision for update;
    insert into public.music_rating_shared as previous (kind, item_id, payload)
    select item.kind, item.item_id, item.payload
    from jsonb_to_recordset(p_items) as item(kind text, item_id text, payload jsonb)
    on conflict (kind, item_id) do update set payload = excluded.payload, updated_at = now()
        where previous.payload is distinct from excluded.payload;
    get diagnostics changed = row_count;
    if changed > 0 then
        update public.music_rating_shared_revision set revision = revision + 1;
    end if;
end;
$$;

revoke all on function public.music_rating_shared_status(boolean),
    public.music_rating_shared_upload(jsonb) from public, anon, authenticated;
grant execute on function public.music_rating_shared_status(boolean),
    public.music_rating_shared_upload(jsonb) to authenticated;

insert into storage.buckets (id, name, public) values
    ('music-rating-shared-artwork', 'music-rating-shared-artwork', false);

create policy music_rating_shared_artwork_boundary on storage.objects
    as restrictive for all to anon, authenticated using (
        bucket_id <> 'music-rating-shared-artwork' or exists (select 1 from public.music_rating_members)
    ) with check (
        bucket_id <> 'music-rating-shared-artwork' or exists (select 1 from public.music_rating_members)
    );
create policy music_rating_shared_artwork_read on storage.objects
    for select to authenticated using (bucket_id = 'music-rating-shared-artwork');
create policy music_rating_shared_artwork_add on storage.objects
    for insert to authenticated with check (bucket_id = 'music-rating-shared-artwork' and name ~ '^[0-9a-f]{64}$');
create policy music_rating_shared_artwork_immutable on storage.objects
    as restrictive for update to anon, authenticated
    using (bucket_id <> 'music-rating-shared-artwork') with check (bucket_id <> 'music-rating-shared-artwork');
create policy music_rating_shared_artwork_keep on storage.objects
    as restrictive for delete to anon, authenticated using (bucket_id <> 'music-rating-shared-artwork');

commit;
