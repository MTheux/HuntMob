// The phone's content box follows the actual decoded display, including rotation.
function fitPhoneFrame(screen, width, height, platform) {
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0||width>8192||height>8192)return;
  const phone=screen.closest('.phone');
  if(!phone)return;
  const ratio=`${width} / ${height}`;
  if(phone.dataset.geometry!==ratio){phone.style.setProperty('--screen-ratio',ratio);phone.dataset.geometry=ratio;}
  phone.dataset.platform=platform;
}
