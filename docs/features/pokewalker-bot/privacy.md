# Pokéwalker privacy information

**What is read.** In channels a server has enabled, Pokéwalker reads the text of enrolled members' messages in memory to count eligible words. Message text is never stored. Messages from members who are not enrolled, or who have opted out, are ignored.

**What is stored.** Server, channel, user and message IDs; message times; per-message step and word counts; step totals; and your game data, such as your Pokémon, items, rewards and progress. Moderators can see game summaries and moderation history, never your message content.

**How long.** Your game data is kept until you delete it, opt out, or a server admin resets your profile. Some records go sooner (backup copies keep everything for up to 28 days, see Backups):
- Step-count records (message ID, channel ID, time, word counts) are kept 24 hours. A message that produced a find or companion candy keeps its message ID and time with your game data until deletion; one that produced an encounter keeps its message ID, channel ID and time until the encounter is deleted. The ❗ reaction record (message and channel ID) stays until you next open `/walker`, or longer if the bot cannot remove the reaction yet.
- A finished encounter and its throw records are deleted about an hour after its result once you close it (at the next sweep if you close it later), or 24 hours after a fled or ran result, or an already stored or sent catch, that you never closed. A catch not yet stored or sent (for example a shiny waiting for you) is kept until you handle it. Raid encounters are kept at least until their raid ends (a World Legendary lasts at most 60 minutes, an EX-Raid at most 24 hours), and the clocks above then apply.
- Gym battle logs and results are kept 2 days (the log you see lives in the battle result; an internal copy goes after 1 hour).
- Only your latest Arena run is kept, with its fight, item and heal records.

Moderation audit entries and active restrictions are kept separately from your profile.

**Gyms.** If you deploy a Pokémon to a server's gym, other members of that server can see it while it defends: its species, form, CP and battle stats, and your Discord user ID as its holder. Challengers' battle logs and results against it are kept for 2 days. If you delete your data, opt out, or a server admin resets your profile, your defender's details are removed from those saved results.

**Raids.** A raid announcement does not say who started it. When you join a raid, the bot records the server, your user ID and that raid. This record is kept after `delete-data` until that raid leaves: at most 60 minutes for a World Legendary, at most 24 hours for an EX-Raid.

**Your controls.**
- `/walker-account privacy` shows this text.
- `/walker-account delete-data` deletes your profile and game data in this server. You can enroll again with `/walker`.
- `/walker-account opt-out` also deletes your profile and stops the bot reading your messages in this server until you run `/walker-account opt-in`.
- An excluded member can still use `privacy`, `delete-data` and `opt-out`, but cannot opt in until the exclusion is lifted.

**Deletion that survives restores.** So that a restored backup can't bring deleted data back, the bot keeps a small deletion log outside the game database. It holds the server ID, user ID, time and, when applicable, the deleted profile ID.

**Backups.** Backups are encrypted and stored on the host and in Google Drive. Backups older than 28 days are deleted from both. If Google Drive is unreachable, deletion there is retried until it succeeds.

**Deletion requests.** You can delete your own data at any time with `delete-data` or `opt-out` above. If you can't (for example, you have left the server), ask that server's administrators: anyone with Manage Server can delete a member's profile with `/walker-admin reset`. For anything a server can't resolve, contact the operator of this bot instance, the person who runs it.
