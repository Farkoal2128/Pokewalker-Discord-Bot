# Pokéwalker privacy information

**What is read.** In channels a server has enabled, Pokéwalker reads the text of enrolled members' messages in memory to count eligible words. Message text is never stored. Messages from members who are not enrolled, or who have opted out, are ignored.

**What is stored.** Server, channel, user and message IDs; message times; step and word-count totals; and your game data, such as your Pokémon, items, rewards and progress. Moderators can see game summaries and moderation history, never your message content.

**How long.** Your game data is kept until you delete it, opt out, or a server admin resets your profile. Moderation audit entries and active restrictions are kept separately from your profile.

**Gyms.** If you deploy a Pokémon to a server's gym, other members of that server can see it while it defends: its species, form, CP and battle stats, and your Discord user ID as its holder. Challengers' battle results against it are saved in their game data. If you delete your data, opt out, or a server admin resets your profile, your defender's details are removed from those saved results.

**Raids.** A World Legendary announcement does not say who started it. When you join a raid, the bot records the server, your user ID and that World Legendary. This record is kept after `delete-data` until that World Legendary leaves, at most 60 minutes.

**Your controls.**
- `/walker-account privacy` shows this text.
- `/walker-account delete-data` deletes your profile and game data in this server. You can enroll again with `/walker`.
- `/walker-account opt-out` also deletes your profile and stops the bot reading your messages in this server until you run `/walker-account opt-in`.
- An excluded member can still use `privacy`, `delete-data` and `opt-out`, but cannot opt in until the exclusion is lifted.

**Deletion that survives restores.** So that a restored backup can't bring deleted data back, the bot keeps a small deletion log outside the game database. It holds the server ID, user ID, time and, when applicable, the deleted profile ID.

**Backups.** Backups are encrypted and stored on the host and in Google Drive. Backups older than 28 days are deleted from both. If Google Drive is unreachable, deletion there is retried until it succeeds.

**Deletion requests.** You can delete your own data at any time with `delete-data` or `opt-out` above. If you can't (for example, you have left the server), ask that server's administrators: anyone with Manage Server can delete a member's profile with `/walker-admin reset`. For anything a server can't resolve, contact the operator of this bot instance, the person who runs it.
