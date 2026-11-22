// THE GROUND THE HILLS LEAVE ALONE (operator 2026-11-22: "make it realistic", "wilderness only", "yes protect").
// The rule the land already keeps: OWNED land is never changed or regenerated — the wilderness is (its edits regrow into
// the untouched planet after RULES.wilderness_regrow_s, 15 minutes: land_server.py regrow). These are the 100 plots
// that held a title on 2026-11-22 (the exec node's assets of land.py ISSUER), the town among them. The rolling hills
// (land-world.js column, ROLL) are multiplied by a mask that is 0 on these plots and rises over ROLL_BLEND metres around
// them, so every owned build stands on the ground it was built on.
// FROZEN: the terrain is a pure function of the place, so this list is a constant — were it read from who owns what now,
// buying a plot would reshape it. A plot titled later is bought as the hills stand.
export const PROTECTED_PLOTS = [
  40922475, 40922476, 40922477, 40922478, 40922479, 40922480, 40922481, 40922482, 40922483, 40922484,
  40930667, 40930668, 40930669, 40930670, 40930671, 40930672, 40930673, 40930674, 40930675, 40930676,
  40938859, 40938860, 40938861, 40938862, 40938863, 40938864, 40938865, 40938866, 40938867, 40938868,
  40947051, 40947052, 40947053, 40947054, 40947055, 40947056, 40947057, 40947058, 40947059, 40947060,
  40955243, 40955244, 40955245, 40955246, 40955247, 40955248, 40955249, 40955250, 40955251, 40955252,
  40963435, 40963436, 40963437, 40963438, 40963439, 40963440, 40963441, 40963442, 40963443, 40963444,
  40971627, 40971628, 40971629, 40971630, 40971631, 40971632, 40971633, 40971634, 40971635, 40971636,
  40979819, 40979820, 40979821, 40979822, 40979823, 40979824, 40979825, 40979826, 40979827, 40979828,
  40988011, 40988012, 40988013, 40988014, 40988015, 40988016, 40988017, 40988018, 40988019, 40988020,
  40996203, 40996204, 40996205, 40996206, 40996207, 40996208, 40996209, 40996210, 40996211, 40996212,
];
